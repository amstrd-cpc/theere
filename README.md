# theere

Record store backend with clean architecture boundaries:
- `core/`: domain + application use-cases (no framework imports)
- `adapters/`: sqlite repositories, Woo/Discogs gateways, notifier, settings provider
- `api/`: FastAPI webhook entrypoint
- `cli/`: Typer CLI entrypoint
- `jobs/`: thin job entrypoints only

## Run

### API
```bash
python run.py api
```

### CLI
```bash
python run.py cli --help
python -m cli.app sync
python -m cli.app sandbox-run
python -m cli.app process-webhook ./payload.json
```

### Worker
```bash
python run.py worker
```

## Guardrail

```bash
python scripts/check_core_imports.py
```

## Webhook

`POST /webhooks/woo?store_id=<id>`

If `store_id` is omitted, default store is used.
