# Fixtures for feature 043 compiled-attempt-checkpoint (target-free).
#
# Bodies are string-identity fixtures for unit tests; they need not compile under forge.
#
# SC mapping:
#   non_vacuous_a.sol  - mechanics-stage style body A (compiled_real)
#   vacuous_b.sol      - compiling but defective/vacuous body B
#   non_vacuous_b.sol  - later non-vacuous body (most-recent wins)
#   noncompiling_c.sol - refused candidate C after DET
