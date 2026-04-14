# Trial 3 Only — Results

> SC connector insertion benchmark (trial_3_only.yaml). Score: T1+T2+T3 total (max ~100).

| Rank | Policy | GT | T1 | T2 | T3 | Total | Date |
|------|--------|----|----|----|----|-------|------|
| 1 | AutoCode | yes | 1.00 | 17.14 | 75.00 | **93.14** | 2026-04-08 19:56 |
| 2 | CheatCode | yes | 1.00 | 16.61 | 75.00 | **92.61** | 2026-04-08 20:29 |
| 3 | AutoCodeJoint | yes | 1.00 | 21.21 | 49.95 | **72.16** | 2026-04-10 13:04 |
| 4 | AutoCodeJoint | yes | 1.00 | 21.19 | 49.95 | **72.14** | 2026-04-10 13:05 |
| 5 | AutoCodeJoint | yes | 1.00 | 21.16 | 49.95 | **72.11** | 2026-04-10 12:18 |
| 6 | AutoCodeJoint | yes | 1.00 | 20.47 | 46.05 | **67.52** | 2026-04-10 12:30 |
| 7 | AutoCode | yes | 1.00 | 16.76 | 46.05 | **63.81** | 2026-04-08 19:53 |
| 8 | AutoCodeJoint | yes | 1.00 | 20.75 | 39.67 | **61.42** | 2026-04-09 23:05 |
| 9 | AutoCodeJoint | yes | 1.00 | 20.69 | 39.67 | **61.36** | 2026-04-08 23:39 |
| 10 | AutoCodeJoint | yes | 1.00 | 20.44 | 39.67 | **61.11** | 2026-04-10 13:06 |
| 11 | AutoCodeJoint | yes | 1.00 | 20.39 | 39.67 | **61.06** | 2026-04-10 13:08 |
| 12 | AutoCodeJoint | yes | 1.00 | 20.39 | 39.67 | **61.06** | 2026-04-10 13:02 |
| 13 | AutoCodeJoint | yes | 1.00 | 18.52 | 39.67 | **59.19** | 2026-04-08 23:05 |
| 14 | CheatCodeJoint | yes | 1.00 | 14.37 | 40.34 | **55.71** | 2026-04-10 12:07 |
| 15 | AutoCodeJoint | yes | 1.00 | 19.94 | 25.00 | **45.94** | 2026-04-08 23:34 |
| 16 | AutoCodeJoint1 | yes | 1.00 | 11.65 | 23.42 | **36.07** | 2026-04-08 22:59 |
| 17 | AutoCodeJoint1 | yes | 1.00 | 13.84 | 2.93 | **17.77** | 2026-04-08 22:53 |
| 18 | AutoCodeJoint1 | yes | 0.00 | 0.00 | 0.00 | **0.00** | 2026-04-08 22:21 |

## Run Details

<details><summary>#1 AutoCode — 93.14 (2026-04-08 19:56:27, gt=yes)</summary>

- **Policy:** `aic_example_policies.ros.AutoCode`

**Trial 3** — T1: 1.00 | T2: 17.14 | T3: 75.00 | Total: 93.14

Tier 2 breakdown:

- **contacts** (0.00): No contact detected.
- **duration** (6.30): Task duration: 31.11 seconds.
- **insertion force** (0.00): No excessive force detected
- **trajectory efficiency** (5.78): Total end-effector path length: 0.36 m, initial plug-port distance: 0.32 m
- **trajectory smoothness** (5.05): Average linear jerk magnitude of the end effector: 7.90 m/s^3

Tier 3: Cable insertion successful.

</details>

<details><summary>#2 CheatCode — 92.61 (2026-04-08 20:29:02, gt=yes)</summary>

- **Policy:** `aic_example_policies.ros.CheatCode`

**Trial 3** — T1: 1.00 | T2: 16.61 | T3: 75.00 | Total: 92.61

Tier 2 breakdown:

- **contacts** (0.00): No contact detected.
- **duration** (5.64): Task duration: 34.15 seconds.
- **insertion force** (0.00): No excessive force detected
- **trajectory efficiency** (5.79): Total end-effector path length: 0.35 m, initial plug-port distance: 0.32 m
- **trajectory smoothness** (5.18): Average linear jerk magnitude of the end effector: 6.83 m/s^3

Tier 3: Cable insertion successful.

</details>

<details><summary>#3 AutoCodeJoint — 72.16 (2026-04-10 13:04:04, gt=yes)</summary>

- **Policy:** `aic_example_policies.ros.AutoCodeJoint`

**Trial 3** — T1: 1.00 | T2: 21.21 | T3: 49.95 | Total: 72.16

Tier 2 breakdown:

- **contacts** (0.00): No contact detected.
- **duration** (10.69): Task duration: 11.01 seconds.
- **insertion force** (0.00): No excessive force detected
- **trajectory efficiency** (5.81): Total end-effector path length: 0.35 m, initial plug-port distance: 0.32 m
- **trajectory smoothness** (4.71): Average linear jerk magnitude of the end effector: 10.73 m/s^3

Tier 3: Partial insertion detected with distance of 0.00m.

</details>

<details><summary>#4 AutoCodeJoint — 72.14 (2026-04-10 13:05:23, gt=yes)</summary>

- **Policy:** `aic_example_policies.ros.AutoCodeJoint`

**Trial 3** — T1: 1.00 | T2: 21.19 | T3: 49.95 | Total: 72.14

Tier 2 breakdown:

- **contacts** (0.00): No contact detected.
- **duration** (10.68): Task duration: 11.03 seconds.
- **insertion force** (0.00): No excessive force detected
- **trajectory efficiency** (5.80): Total end-effector path length: 0.35 m, initial plug-port distance: 0.32 m
- **trajectory smoothness** (4.70): Average linear jerk magnitude of the end effector: 10.84 m/s^3

Tier 3: Partial insertion detected with distance of 0.00m.

</details>

<details><summary>#5 AutoCodeJoint — 72.11 (2026-04-10 12:18:28, gt=yes)</summary>

- **Policy:** `aic_example_policies.ros.AutoCodeJoint`

**Trial 3** — T1: 1.00 | T2: 21.16 | T3: 49.95 | Total: 72.11

Tier 2 breakdown:

- **contacts** (0.00): No contact detected.
- **duration** (10.68): Task duration: 11.04 seconds.
- **insertion force** (0.00): Insertion force above 20.00 N, detected for a time of 0.02 seconds. Max detected force: 27.32N. This is below the threshold of 1.00 seconds. Penalty not applied.
- **trajectory efficiency** (5.79): Total end-effector path length: 0.35 m, initial plug-port distance: 0.32 m
- **trajectory smoothness** (4.68): Average linear jerk magnitude of the end effector: 10.97 m/s^3

Tier 3: Partial insertion detected with distance of 0.00m.

</details>

<details><summary>#6 AutoCodeJoint — 67.52 (2026-04-10 12:30:00, gt=yes)</summary>

- **Policy:** `aic_example_policies.ros.AutoCodeJoint`

**Trial 3** — T1: 1.00 | T2: 20.47 | T3: 46.05 | Total: 67.52

Tier 2 breakdown:

- **contacts** (0.00): No contact detected.
- **duration** (10.02): Task duration: 14.09 seconds.
- **insertion force** (0.00): No excessive force detected
- **trajectory efficiency** (5.82): Total end-effector path length: 0.35 m, initial plug-port distance: 0.32 m
- **trajectory smoothness** (4.63): Average linear jerk magnitude of the end effector: 11.43 m/s^3

Tier 3: Partial insertion detected with distance of 0.01m.

</details>

<details><summary>#7 AutoCode — 63.81 (2026-04-08 19:53:46, gt=yes)</summary>

- **Policy:** `aic_example_policies.ros.AutoCode`

**Trial 3** — T1: 1.00 | T2: 16.76 | T3: 46.05 | Total: 63.81

Tier 2 breakdown:

- **contacts** (0.00): No contact detected.
- **duration** (5.87): Task duration: 33.08 seconds.
- **insertion force** (0.00): No excessive force detected
- **trajectory efficiency** (5.82): Total end-effector path length: 0.35 m, initial plug-port distance: 0.32 m
- **trajectory smoothness** (5.07): Average linear jerk magnitude of the end effector: 7.78 m/s^3

Tier 3: Partial insertion detected with distance of 0.01m.

</details>

<details><summary>#8 AutoCodeJoint — 61.42 (2026-04-09 23:05:59, gt=yes)</summary>

- **Policy:** `aic_example_policies.ros.AutoCodeJoint`

**Trial 3** — T1: 1.00 | T2: 20.75 | T3: 39.67 | Total: 61.42

Tier 2 breakdown:

- **contacts** (0.00): No contact detected.
- **duration** (10.89): Task duration: 10.09 seconds.
- **insertion force** (0.00): No excessive force detected
- **trajectory efficiency** (5.84): Total end-effector path length: 0.35 m, initial plug-port distance: 0.32 m
- **trajectory smoothness** (4.02): Average linear jerk magnitude of the end effector: 16.51 m/s^3

Tier 3: Partial insertion detected with distance of 0.01m.

</details>

<details><summary>#9 AutoCodeJoint — 61.36 (2026-04-08 23:39:11, gt=yes)</summary>

- **Policy:** `aic_example_policies.ros.AutoCodeJoint`

**Trial 3** — T1: 1.00 | T2: 20.69 | T3: 39.67 | Total: 61.36

Tier 2 breakdown:

- **contacts** (0.00): No contact detected.
- **duration** (10.89): Task duration: 10.07 seconds.
- **insertion force** (0.00): No excessive force detected
- **trajectory efficiency** (5.85): Total end-effector path length: 0.34 m, initial plug-port distance: 0.32 m
- **trajectory smoothness** (3.95): Average linear jerk magnitude of the end effector: 17.12 m/s^3

Tier 3: Partial insertion detected with distance of 0.01m.

</details>

<details><summary>#10 AutoCodeJoint — 61.11 (2026-04-10 13:06:39, gt=yes)</summary>

- **Policy:** `aic_example_policies.ros.AutoCodeJoint`

**Trial 3** — T1: 1.00 | T2: 20.44 | T3: 39.67 | Total: 61.11

Tier 2 breakdown:

- **contacts** (0.00): No contact detected.
- **duration** (10.03): Task duration: 14.02 seconds.
- **insertion force** (0.00): Insertion force above 20.00 N, detected for a time of 0.02 seconds. Max detected force: 53.32N. This is below the threshold of 1.00 seconds. Penalty not applied.
- **trajectory efficiency** (5.88): Total end-effector path length: 0.34 m, initial plug-port distance: 0.32 m
- **trajectory smoothness** (4.53): Average linear jerk magnitude of the end effector: 12.26 m/s^3

Tier 3: Partial insertion detected with distance of 0.01m.

</details>

<details><summary>#11 AutoCodeJoint — 61.06 (2026-04-10 13:08:03, gt=yes)</summary>

- **Policy:** `aic_example_policies.ros.AutoCodeJoint`

**Trial 3** — T1: 1.00 | T2: 20.39 | T3: 39.67 | Total: 61.06

Tier 2 breakdown:

- **contacts** (0.00): No contact detected.
- **duration** (10.03): Task duration: 14.05 seconds.
- **insertion force** (0.00): Insertion force above 20.00 N, detected for a time of 0.02 seconds. Max detected force: 21.05N. This is below the threshold of 1.00 seconds. Penalty not applied.
- **trajectory efficiency** (5.88): Total end-effector path length: 0.34 m, initial plug-port distance: 0.32 m
- **trajectory smoothness** (4.49): Average linear jerk magnitude of the end effector: 12.56 m/s^3

Tier 3: Partial insertion detected with distance of 0.01m.

</details>

<details><summary>#12 AutoCodeJoint — 61.06 (2026-04-10 13:02:51, gt=yes)</summary>

- **Policy:** `aic_example_policies.ros.AutoCodeJoint`

**Trial 3** — T1: 1.00 | T2: 20.39 | T3: 39.67 | Total: 61.06

Tier 2 breakdown:

- **contacts** (0.00): No contact detected.
- **duration** (10.03): Task duration: 14.03 seconds.
- **insertion force** (0.00): No excessive force detected
- **trajectory efficiency** (5.89): Total end-effector path length: 0.34 m, initial plug-port distance: 0.32 m
- **trajectory smoothness** (4.47): Average linear jerk magnitude of the end effector: 12.76 m/s^3

Tier 3: Partial insertion detected with distance of 0.01m.

</details>

<details><summary>#13 AutoCodeJoint — 59.19 (2026-04-08 23:05:42, gt=yes)</summary>

- **Policy:** `aic_example_policies.ros.AutoCodeJoint`

**Trial 3** — T1: 1.00 | T2: 18.52 | T3: 39.67 | Total: 59.19

Tier 2 breakdown:

- **contacts** (0.00): No contact detected.
- **duration** (7.81): Task duration: 24.19 seconds.
- **insertion force** (0.00): No excessive force detected
- **trajectory efficiency** (5.75): Total end-effector path length: 0.36 m, initial plug-port distance: 0.32 m
- **trajectory smoothness** (4.96): Average linear jerk magnitude of the end effector: 8.69 m/s^3

Tier 3: Partial insertion detected with distance of 0.01m.

</details>

<details><summary>#14 CheatCodeJoint — 55.71 (2026-04-10 12:07:55, gt=yes)</summary>

- **Policy:** `aic_example_policies.ros.CheatCodeJoint`

**Trial 3** — T1: 1.00 | T2: 14.37 | T3: 40.34 | Total: 55.71

Tier 2 breakdown:

- **contacts** (0.00): No contact detected.
- **duration** (4.12): Task duration: 41.13 seconds.
- **insertion force** (0.00): No excessive force detected
- **trajectory efficiency** (5.68): Total end-effector path length: 0.37 m, initial plug-port distance: 0.32 m
- **trajectory smoothness** (4.57): Average linear jerk magnitude of the end effector: 11.93 m/s^3

Tier 3: Partial insertion detected with distance of 0.01m.

</details>

<details><summary>#15 AutoCodeJoint — 45.94 (2026-04-08 23:34:23, gt=yes)</summary>

- **Policy:** `aic_example_policies.ros.AutoCodeJoint`

**Trial 3** — T1: 1.00 | T2: 19.94 | T3: 25.00 | Total: 45.94

Tier 2 breakdown:

- **contacts** (0.00): No contact detected.
- **duration** (11.99): Task duration: 5.04 seconds.
- **insertion force** (0.00): Insertion force above 20.00 N, detected for a time of 0.04 seconds. Max detected force: 32.72N. This is below the threshold of 1.00 seconds. Penalty not applied.
- **trajectory efficiency** (5.84): Total end-effector path length: 0.35 m, initial plug-port distance: 0.32 m
- **trajectory smoothness** (2.11): Average linear jerk magnitude of the end effector: 32.42 m/s^3

Tier 3: No insertion detected. Final plug port distance: 0.01m.

</details>

<details><summary>#16 AutoCodeJoint1 — 36.07 (2026-04-08 22:59:43, gt=yes)</summary>

- **Policy:** `aic_example_policies.ros.AutoCodeJoint1`

**Trial 3** — T1: 1.00 | T2: 11.65 | T3: 23.42 | Total: 36.07

Tier 2 breakdown:

- **contacts** (0.00): No contact detected.
- **duration** (4.32): Task duration: 40.18 seconds.
- **insertion force** (0.00): Insertion force above 20.00 N, detected for a time of 0.08 seconds. Max detected force: 107.97N. This is below the threshold of 1.00 seconds. Penalty not applied.
- **trajectory efficiency** (5.49): Total end-effector path length: 0.40 m, initial plug-port distance: 0.32 m
- **trajectory smoothness** (1.84): Average linear jerk magnitude of the end effector: 34.68 m/s^3

Tier 3: No insertion detected. Final plug port distance: 0.03m.

</details>

<details><summary>#17 AutoCodeJoint1 — 17.77 (2026-04-08 22:53:07, gt=yes)</summary>

- **Policy:** `aic_example_policies.ros.AutoCodeJoint1`

**Trial 3** — T1: 1.00 | T2: 13.84 | T3: 2.93 | Total: 17.77

Tier 2 breakdown:

- **contacts** (0.00): No contact detected.
- **duration** (4.76): Task duration: 38.17 seconds.
- **insertion force** (0.00): No excessive force detected
- **trajectory efficiency** (6.00): Total end-effector path length: 0.22 m, initial plug-port distance: 0.32 m
- **trajectory smoothness** (3.08): Average linear jerk magnitude of the end effector: 24.37 m/s^3

Tier 3: No insertion detected. Final plug port distance: 0.16m.

</details>

<details><summary>#18 AutoCodeJoint1 — 0.00 (2026-04-08 22:21:10, gt=yes)</summary>

- **Policy:** `aic_example_policies.ros.AutoCodeJoint1`

**Trial 3** — T1: 0.00 | T2: 0.00 | T3: 0.00 | Total: 0.00

Tier 3: Task execution failed

</details>
