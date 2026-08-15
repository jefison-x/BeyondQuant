# Migration Policy

## Legacy references

- Community reference: `/home/jefison/projects/BeyondQuant-community`
- Community GitHub repository: `jefison-x/BeyondQuant-Community`
- Historical GitHub repository: `jefison-x/BeyondQuant-Legacy`

The Community repository is a READ-ONLY reference during new-project work. Neither the Community nor Legacy repository is the Git history of this project.

## Migration policy

Legacy code is source material, not architectural authority. The new architecture takes precedence over old implementation structure, runtime choices, and service boundaries.

Before implementing a legacy capability:

1. Inspect the old implementation as reference material.
2. Identify the domain invariant and required contract.
3. Classify the legacy module.
4. Implement the capability cleanly in the new architecture.
5. Add tests and contracts before broad adoption.

Legacy modules must eventually be classified in `legacy-inventory.md` as one of:

- `MIGRATE`
- `REFACTOR`
- `CONTRACT-ONLY`
- `DROP`

No legacy module may be copied into this repository without an explicit inventory decision and architecture review.
