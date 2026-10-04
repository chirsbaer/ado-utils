# ado-utils

Small command-line utilities for working with **Azure DevOps Boards**, built
on top of the [Azure CLI](https://learn.microsoft.com/cli/azure/) and its
`azure-devops` extension. Each tool lives in its own folder with its own README.

## Tools

| Tool | What it's for | Language |
| --- | --- | --- |
| [ado-iteration-archiver](ado-iteration-archiver/) | Clean up the iteration tree: find iterations by name (e.g. all `2021` sprints) and move them under an archive folder | Bash |
| [ado-iteration-summary](ado-iteration-summary/) | Sprint overview for a team: total effort and work item counts for the current and next iteration, optionally with completed vs. leftover effort for past iterations | Python |

## Common prerequisites

All tools need:

- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) (`az`)
- The Azure DevOps extension:
  ```bash
  az extension add --name azure-devops
  ```
- To be signed in, with `az login` or a personal access token:
  ```bash
  az devops login --organization https://dev.azure.com/YourOrg/
  ```

Each tool's README lists anything extra it needs (e.g. `jq` for the archiver,
Python 3 for the summary) and the permissions required.

## Getting started

```bash
git clone https://github.com/chirsbaer/ado-utils.git
cd ado-utils
```

Then open the README of the tool you want to use.

## License

[MIT](LICENSE)
