# Publishing a test infobase on Linux

The debug services and any HTTP service under test need the infobase published through a web
server with the 1C web-server extension module (`wsap24.so`). On Windows use `1c-web-ops`
(`1c-metadata-manage` skill). On Linux there are two ways; the first needs no root and is the one
to use for an agent's test environment.

Common requirements:

- The platform component «Модули расширения веб-сервера» is installed:
  `<platform>/wsap24.so` exists. Without it nothing below works — install it from the platform
  distribution.
- Apache HTTP Server 2.4 (Debian/Ubuntu package `apache2`) with the **prefork** MPM: the 1C module
  does not work with `event` / `worker`.
- Apache runs as a user that can read and write the file infobase directory.
- HTTP services of extensions are published only with
  `<httpServices publishByDefault="true" publishExtensionsByDefault="true"/>` in `default.vrd`.
  Without the second attribute they answer **404** to an authenticated request, while an
  unauthenticated one still gets 401 and looks published.

`.dev.env` of the project gets `INFOBASE_PUBLISH_URL=http://localhost:<port>/<publication>` — the
scripts of this skill read it.

## A. Without root — a private Apache instance (recommended)

The distribution binary runs with its own server root and configuration; the system Apache service
is not touched and not needed.

1. **Layout** — a directory outside the repository or ignored by git, for example `tmp/apache`:

   ```bash
   A=$PWD/tmp/apache
   mkdir -p $A/bin $A/conf $A/logs
   ln -s /usr/sbin/apache2 $A/bin/httpd
   ```

2. **`$A/conf/httpd.conf`** — the distribution binary has no modules built in:

   ```apache
   ServerRoot "<A>"
   PidFile <A>/logs/httpd.pid
   ErrorLog <A>/logs/error.log
   LoadModule mpm_prefork_module /usr/lib/apache2/modules/mod_mpm_prefork.so
   LoadModule authz_core_module  /usr/lib/apache2/modules/mod_authz_core.so
   LoadModule alias_module       /usr/lib/apache2/modules/mod_alias.so
   ServerName localhost
   Timeout 600
   ```

3. **Publish** with `web-publish.py` of `1c-web-ops`: it writes `default.vrd` (with extension
   services enabled), adds `Listen` and the publication block to `httpd.conf` and starts the server
   with `-d <A> -f <A>/conf/httpd.conf`:

   ```bash
   python3 <tools>/skills/1c-metadata-manage/tools/1c-web-ops/scripts/web-publish.py \
     -InfoBasePath <INFOBASE_PATH> -AppName <publication> -ApachePath $A -Port 8080
   ```

   Do not pass `-UserName` / `-Password` here: they would be written into `default.vrd`. Clients
   authenticate themselves.
4. **Restart** after loading a changed extension or configuration — web sessions cache metadata:
   run the same `web-publish.py` command again (it restarts its own server).
5. **Stop** — the PIDs of this instance are the processes whose command line carries `-d <A>`:
   `kill $(cat $A/logs/httpd.pid)`.

## B. With root — the system Apache service

For a shared machine where the publication should survive reboots of the session.

```bash
sudo apt-get install -y apache2
sudo a2dismod mpm_event mpm_worker; sudo a2enmod mpm_prefork
# run Apache as the owner of the infobase files
sudo sed -i 's/^export APACHE_RUN_USER=.*/export APACHE_RUN_USER=<user>/;s/^export APACHE_RUN_GROUP=.*/export APACHE_RUN_GROUP=<group>/' /etc/apache2/envvars
```

Site `/etc/apache2/sites-available/<site>.conf`:

```apache
<IfModule !mod_1cws.c>
    LoadModule _1cws_module <platform>/wsap24.so
</IfModule>
Listen 8080
<VirtualHost *:8080>
    Alias "/<publication>" "<publication dir>"
    <Directory "<publication dir>">
        AllowOverride All
        Options None
        Require all granted
        SetHandler 1c-application
        ManagedApplicationDescriptor "<publication dir>/default.vrd"
    </Directory>
</VirtualHost>
```

`<publication dir>/default.vrd`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<point xmlns="http://v8.1c.ru/8.2/virtual-resource-system"
       xmlns:xs="http://www.w3.org/2001/XMLSchema"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       base="/<publication>"
       ib="File=&quot;<INFOBASE_PATH>&quot;;">
    <ws pointEnableCommon="false"/>
    <httpServices publishByDefault="true" publishExtensionsByDefault="true"/>
</point>
```

`sudo a2ensite <site> && sudo apachectl configtest && sudo systemctl restart apache2`. Autostart is
a decision of the machine owner: `systemctl disable apache2` keeps the service manual.

## Check

`python3 <skill>/scripts/check-services.py` — both debug services 200. Typical answers:

| Answer | Meaning |
|---|---|
| server does not answer | web server not running, wrong port in `INFOBASE_PUBLISH_URL` |
| 404 without authentication | publication path wrong (`Alias`, `base` in `default.vrd`) |
| 401 without, 404 with authentication | extension not loaded, or `publishExtensionsByDefault` missing |
| 403 | the user of `.dev.env` lacks full rights |
| 200 | ready |

`<A>/logs/error.log` (variant A) or `/var/log/apache2/error.log` (variant B) has the reason when the
server does not start; `apache2 -t -d <A> -f <A>/conf/httpd.conf` checks the configuration.
