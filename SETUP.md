# M0ST — Setup Guide

Complete setup instructions for **Linux** and **Windows**.

---

## Prerequisites

| Requirement | Version | Notes                                 |
| ----------- | ------- | ------------------------------------- |
| Python      | 3.10+   | 3.11 recommended                      |
| pip         | Latest  | `python -m pip install --upgrade pip` |
| Git         | Any     | For cloning the repository            |

### Optional Tools (enable additional agents)

| Tool             | Agent                 | Notes                        |
| ---------------- | --------------------- | ---------------------------- |
| radare2 + r2pipe | Static analysis       | Core disassembly engine      |
| GDB + pygdbmi    | Dynamic tracing       | Linux only                   |
| Ghidra           | Pseudocode extraction | Headless decompiler          |
| z3-solver        | Verification          | Falls back to stub if absent |

### Optional AI Dependencies

| Package                 | Purpose                       | Notes                         |
| ----------------------- | ----------------------------- | ----------------------------- |
| openai                  | OpenAI / Ollama LLM inference | Also works with local models  |
| anthropic               | Anthropic Claude inference    |                               |
| mistralai               | Mistral AI inference          |                               |
| torch + torch-geometric | GNN graph embeddings          | Falls back to manual features |

---

## 1. Clone and Set Up

```bash
git clone https://github.com/CYB3R-BO1/M0ST.git
cd M0ST
```

### Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Windows (cmd)

```cmd
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

---

## 2. Configure Environment

Copy the example config and edit as needed:

```bash
cp config.yml.example config.yml
```

The `config.yml` file supports:

- `sqlite.db_path` — SQLite database location
- `tools.r2_path`, `tools.gdb_path`, `tools.ghidra_path` — Custom tool paths
- `llm.provider` — LLM backend: `openai`, `anthropic`, `mistral`, `local`, or `none`
- `llm.model` — Model name (e.g. `gpt-4o`, `claude-sonnet-4-20250514`)
- `llm.api_key` — API key (can also use env vars: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`)
- `llm.base_url` — For local/Ollama: `http://localhost:11434/v1`
- `gnn.model_path` — Path to a trained GNN checkpoint (`.pt` file)
- `gnn.architecture` — `gat`, `graphsage`, or `gine`
- `pipeline.event_timeout_seconds` — Pipeline timeout

> **Note:** M0ST works fully without any LLM or GNN configuration.
> All AI features fall back to classical heuristics when providers are unavailable.

---

## 3. Install Optional Tools

### radare2 (recommended)

**Linux:**

```bash
git clone https://github.com/radareorg/radare2.git
cd radare2 && sys/install.sh
pip install r2pipe
```

**Windows:**
Download from [radare2 releases](https://github.com/radareorg/radare2/releases) and add to PATH.

```cmd
pip install r2pipe
```

### Ghidra (optional — for pseudocode)

Download from [ghidra-sre.org](https://ghidra-sre.org/) and set `tools.ghidra_path` in `config.yml` to the path of `analyzeHeadless`.

### GDB (Linux only)

```bash
sudo apt install gdb
pip install pygdbmi
```

### Z3 Solver

```bash
pip install z3-solver
```

### LLM Providers (pick one)

```bash
# OpenAI (also works with Ollama via compatible API)
pip install openai

# Anthropic Claude
pip install anthropic

# Mistral AI
pip install mistralai
```

### GNN / PyTorch (optional)

```bash
pip install torch torch-geometric torch-scatter torch-sparse numpy
```

### Local LLM via Ollama

```bash
# Install Ollama: https://ollama.ai
ollama pull llama3
# Set in config.yml:
#   llm.provider: local
#   llm.base_url: http://localhost:11434/v1
#   llm.model: llama3
```

---

## 4. Run M0ST

### Interactive CLI (default)

```bash
python main.py
```

### Direct binary analysis

```bash
python main.py path/to/binary
```

### Docker

```bash
cd docker
docker compose up -d
docker compose exec spider python main.py
```

---

## 5. Verify Installation

Once inside the CLI, type `status` to check tool availability:

```
spider> status

Tool/Service Status:
  [+] r2pipe: OK
  [+] radare2: OK
  [-] gdb: NOT FOUND
  [-] pygdbmi: NOT FOUND
  [+] z3-solver: OK
  [+] openai: OK
  [-] torch-geometric: NOT FOUND
```

Tools marked `NOT FOUND` will use fallback implementations.

---

## 6. Quick Test

Once inside the CLI, you will first see the **module selection menu**:

```
  Select analysis modules to enable:
    [1] Reverse Engineering
    [2] AI Binary Intelligence
    [3] Network Traffic Analysis
    [0] Full Mode (all modules)

  Enter choice (default: 0 — Full Mode):
```

Press **Enter** (or type `0`) for Full Mode. Then try:

```
m0st> status                         # Check tool availability
m0st> load tests/binaries/ret        # Disassemble a test binary
m0st> list funcs                     # List discovered functions
m0st> complexity                     # Show cyclomatic complexity
m0st> ai full                        # Full AI analysis pipeline
m0st> ai name 0x401000               # AI-suggested function name
m0st> ai ask what does this do?      # Free-form AI query
m0st> plugins list                   # Available plugins
m0st> export report.json             # Export analysis results
m0st> verbose on                     # Enable verbose pipeline output
m0st> verbose off                    # Quiet mode (spinner only)
m0st> help                           # Help index
m0st> help ai                        # AI command help
m0st> quit
```

**Verbose mode:** By default the pipeline runs in quiet mode with an animated spinner showing progress. Use `verbose on` to see all agent output, or launch with `python main.py --verbose`.

---

## Troubleshooting

| Issue                         | Solution                                                                                     |
| ----------------------------- | -------------------------------------------------------------------------------------------- |
| `ModuleNotFoundError`         | Activate venv and run `pip install -r requirements.txt`                                      |
| `r2pipe` import fails         | Install radare2 and add to PATH                                                              |
| LLM returns empty             | Check `config.yml` for correct `llm.provider` and `llm.api_key`                              |
| GNN fallback active           | Install `torch` and `torch-geometric`, or provide a model checkpoint                         |
| Pipeline timeout              | Increase `pipeline.event_timeout_seconds` in `config.yml`                                    |
| Windows path errors           | Use forward slashes or raw strings in paths                                                  |
| r2 INFO/WARN lines visible    | Use `verbose off` (default) — set `e log.level=0` is applied automatically                   |
| `VulnerabilityDetector` error | Ensure `security_modules/` package is on `sys.path` (use `python main.py` from project root) |
