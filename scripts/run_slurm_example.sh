#!/bin/bash
# Example: run the turbulent heated pipe on a SLURM cluster with the human approval gate.
# Adjust the environment variables for your site (module names, bashrc, partition/account in the spec).
export NUAGENT_SLURM_MODULES="openfoam/2412"          # or set NUAGENT_FOAM_BASHRC=/path/to/etc/bashrc
export NUAGENT_SLURM_EXTRA="--mem=32G"
nuagent run examples/heated_pipe/turbulent_slurm.yaml --executor slurm   # pauses for approval
# nuagent run examples/heated_pipe/turbulent_slurm.yaml --executor slurm --auto-approve
