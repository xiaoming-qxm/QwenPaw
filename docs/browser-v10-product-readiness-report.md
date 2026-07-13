# Browser V10 Product Readiness Report

- Status: `blocked`
- Scenario count: `8`
- Backend route: `browser(code=...) -> context="auto" -> unavailable`

## Gates

| Gate | Status |
|---|---|
| `truth_gates` | `passed` |
| `risk_gates` | `passed` |
| `service_preflight` | `passed` |
| `scenario_matrix` | `blocked` |
| `lifecycle_gates` | `passed` |

## Scenarios

| Scenario | Status | Context | Backend |
|---|---|---|---|
| `public-search-isolated` | `passed` | `isolated` | `isolated.playwright` |
| `user-observation` | `blocked` | `user` | `user.chrome_extension` |
| `local-cart-approval` | `blocked` | `isolated` | `isolated.playwright` |
| `local-cart-auto` | `blocked` | `isolated` | `isolated.playwright` |
| `complex-isolated-fixture` | `failed` | `isolated` | `isolated.playwright` |
| `complex-user-fixture` | `blocked` | `user` | `user.chrome_extension` |
| `bridge-disconnect` | `blocked` | `user` | `user.chrome_extension` |
| `cleanup-cancel` | `blocked` | `user` | `user.chrome_extension` |

## Cleanup

- Cleanup summary: `{'cleanup_ok': True, 'residual_tab_count': 0, 'kernel_idle_count': 0, 'bridge_connected': False}`
