# Whole binaries — CF / CFE / EPF

### CLI commands

#### Extract (`-E`)

```bash
python -m v8unpack -E "<file.cf>" "<sources_dir>" --temp "<temp_dir>"
```

| Parameter | Description |
|-----------|-------------|
| `<file.cf>` | Path to a CF, CFE or EPF file |
| `<sources_dir>` | Destination for the unpacked sources (created automatically) |
| `--temp <path>` | Folder for intermediate data (kept, not deleted — useful for debugging) |
| `--processes N` | Number of worker processes (default: `cpu_count - 2`) |
| `--descent XYYZZZ` | Extension versioning mode (configuration version suffix) |
| `--auto_include` | Build the table of contents dynamically from the folder, not from the header |
| `--prefix STR` | Prefix for first-level metadata names |

#### Build (`-B`)

```bash
python -m v8unpack -B "<sources_dir>" "<file.cf>"
```

**`-B` rebuilds what `-E` wrote — it is not a way to produce a `.cf` for loading
into an infobase of a current configuration.** On a real 8.3.27 configuration the
round trip degraded the metadata: XML descriptors of version 3 came back as
version 2 (`Задача`), standard attributes broke, objects dropped out of the
exchange-plan content (УРБД). The library decodes metadata through its own,
version-bounded parsers, and what it does not know it does not write back. Use it
for a data processor / extension you extracted with the same version, or to
inspect; a configuration goes back into an infobase only through the platform
(`/LoadConfigFromFiles` from the Designer file export, or `/LoadCfg` of a file the
platform wrote).

| Parameter | Description |
|-----------|-------------|
| `<sources_dir>` | Folder with the unpacked sources |
| `<file.cf>` | Path to the output CF / CFE / EPF file |
| `--index <path>` | JSON table-of-contents file (maps files across folders) |
| `--version XYYZZ` | Compatibility-mode version (for extensions), e.g. `80306` = 8.3.6 |
| `--descent XYYZZZ` | Configuration version suffix |

#### Index (`-I`)

```bash
python -m v8unpack -I "<sources_dir>" --index index.json --core core
```

Generates / updates `index.json` — the table-of-contents file that controls how sources
are laid out across subfolders.

#### Batch operations (`-EA`, `-BA`, `-IA`)

```bash
python -m v8unpack -EA products.json              # extract all products
python -m v8unpack -BA products.json              # build all products
python -m v8unpack -BA products.json --index KEY  # build a specific product
```

`products.json` describes several products with their individual build parameters.

### Python API

```python
import v8unpack

v8unpack.extract('d:/sample.cf', 'd:/src')
v8unpack.extract('d:/sample.cf', 'd:/src', temp_dir='d:/temp',
                 options={'descent': 4100200, 'auto_include': True})

v8unpack.build('d:/src', 'd:/repacked.cf')
v8unpack.build('d:/src', 'd:/repacked.cf', index='index.json',
               options={'descent': 4100200, 'version': '80306'})
```

### Examples

#### Extract a configuration

```bash
python -m v8unpack -E "<project>/1Cv8.cf" "<project>/src" --temp "<project>/temp"
```

#### Build it back

```bash
python -m v8unpack -B "<project>/src" "<project>/1Cv8_new.cf"
```

#### Extract an external data processor

```bash
python -m v8unpack -E "MyDataProcessor.epf" "src_epf"
```

#### Extract an extension

```bash
python -m v8unpack -E "MyExtension.cfe" "src_cfe" --descent 3000112
```

#### Build an extension

```bash
python -m v8unpack -B "src_cfe" "bin/ext.cfe" --index cmd/index.json --descent 3000112 --version 80316
```

### Version compatibility

The utility version is recorded in `Configuration.json` (`"v8unpack": "1.2.6"`). On
build, `major.minor` must match. If the versions differ:

1. Build with the old version.
2. Upgrade the utility.
3. Re-extract with the new version.
4. Commit.

### Intermediate stages (`--temp`)

| Stage | Description |
|-------|-------------|
| `decode_stage_0/` | Extraction from the 1C container |
| `decode_stage_1/` | Decompression (zlib), bracket-files |
| `decode_stage_3/` | Metadata parsing → tree |
| Destination folder | Code organization (include, form elements) |
