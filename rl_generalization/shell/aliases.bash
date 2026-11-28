# Source this file. Functions deliberately resolve paths from this checkout.
OMX_RL_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# Remove legacy aliases so functions of the same names can be defined.
unalias rl cdrl crootrl 2>/dev/null || true
function rl { source "$OMX_RL_ROOT/.venvs/rl/bin/activate"; }
function crootrl { cd "$OMX_RL_ROOT"; }
function cdrl { cd "$OMX_RL_ROOT/versions/$(cat "$OMX_RL_ROOT/CURRENT")"; }
function rltrain { bash "$OMX_RL_ROOT/run.sh" train "$@"; }
function rleval { bash "$OMX_RL_ROOT/run.sh" evaluate "$@"; }
function rltest { bash "$OMX_RL_ROOT/run.sh" test "$@"; }
