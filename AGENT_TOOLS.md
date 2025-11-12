# Cursor Agent Tooling

| Tool                      | Purpose                                                             |
| ------------------------- | ------------------------------------------------------------------- |
| `codebase_search`         | Semantic search for understanding unfamiliar code.                  |
| `grep`                    | Regex-based search using ripgrep within the workspace.              |
| `read_file`               | Read file contents (optionally with offsets and limits).            |
| `list_dir`                | List directory contents, respecting ignore rules.                   |
| `glob_file_search`        | Find files by name patterns.                                        |
| `run_terminal_cmd`        | Propose terminal commands (executes after user approval).           |
| `apply_patch`             | Apply textual diffs to files via patch semantics.                   |
| `edit_file`               | Provide explicit code edits when `apply_patch` is unsuitable.       |
| `edit_notebook`           | Modify Jupyter notebook cells.                                      |
| `delete_file`             | Remove files from the workspace.                                    |
| `todo_write`              | Manage the task todo list.                                          |
| `read_lints`              | Retrieve IDE linter warnings/errors.                                |
| `web_search`              | Query the web for up-to-date information.                           |
| `update_memory`           | Persist or update user-specific memory (requires explicit request). |
| `multi_tool_use.parallel` | Run multiple tool calls in parallel (where supported).              |
