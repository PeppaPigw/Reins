# Standalone Orchestration Scripts

These scripts wrap the native Reins orchestration APIs without going through the CLI command surface.

## Available scripts

- `scripts/run_pipeline.py`: run a single pipeline YAML against one task directory
- `scripts/run_batch.py`: run one pipeline across every child task directory in a parent folder

## Usage

```bash
python3 scripts/run_pipeline.py .reins/pipelines/standard.yaml \
  --task-dir .reins/tasks/04-19-example-task \
  --output .reins/pipeline-output/example
```

```bash
python3 scripts/run_batch.py .reins/pipelines/standard.yaml \
  .reins/tasks \
  --output .reins/batch-output \
  --parallel 2
```

Both scripts write:

- `result.json`: machine-readable summary
- `summary.md`: human-readable summary
- `<stage-name>.txt`: captured stage output
- `pipeline-state.json`: copied from the task directory when present
