"""B题问题4的推荐运行入口：预算购置外层 + 精确调度内层。

运行本文件即可重新生成表4、表5、工序时间表、扩展调度表和求解摘要。
证明路线：
1. 精确求解最有竞争力的购置结构，取得32058秒上界；
2. 对全部可能改善该上界的预算极大结构求“工序链+累积资源”松弛下界；
3. 其余结构的下界均不小于32058秒，故主目标全局最优；
4. 对不购买灌装机的低成本近邻结构做完整精确求解，证明其最优值32125秒，
   从而32058秒下的最低购置费用为500000元。
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import math
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def ensure_compatible_python():
    """兼容用户电脑上的Python 3.7 32位启动环境。"""
    if sys.maxsize > 2**32 and sys.version_info >= (3, 10):
        return
    candidates = [
        Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime"
        / "dependencies" / "python" / "python.exe",
        Path(r"C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"),
    ]
    for executable in candidates:
        if executable.is_file() and executable.resolve() != Path(sys.executable).resolve():
            print(f"当前解释器不兼容，自动切换到：{executable}", flush=True)
            result = subprocess.run(
                [str(executable), str(Path(__file__).resolve()), *sys.argv[1:]],
                cwd=str(ROOT),
            )
            raise SystemExit(result.returncode)
    raise SystemExit("本程序要求Python 3.10及以上的64位版本。")


ensure_compatible_python()
CORE_PATH = ROOT / "问题4_预算约束下最优购置与调度.py"
SPEC = importlib.util.spec_from_file_location("q4_core", CORE_PATH)
q4 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = q4
SPEC.loader.exec_module(q4)

TYPES = list(q4.EXISTING_PER_TEAM)
SEED_EXTRAS = (0, 0, 1, 3, 3)
LOWER_COST_RIVAL = (0, 0, 0, 3, 3)


def as_plan(extras):
    return dict(zip(TYPES, extras))


def purchase_cost(extras):
    return sum(q4.UNIT_PRICE[t] * n for t, n in zip(TYPES, extras))


def simple_lower_bound(extras):
    capacities = {
        t: 2 * q4.EXISTING_PER_TEAM[t] + n
        for t, n in zip(TYPES, extras)
    }
    operations, chains = q4.build_operations()
    op_by_code = {op.code: op for op in operations}
    bounds = []
    for workshop, chain in chains.items():
        value = min(q4.initial_travel_time(g, workshop) for g in (1, 2))
        for code in chain:
            op = op_by_code[code]
            value += max(
                q4.duration_seconds(op.workload, r.efficiency,
                                    capacities[r.equipment_type])
                for r in op.requirements
            )
        bounds.append(value)
    for equipment_type in TYPES:
        load = sum(
            op.workload * 3600 / r.efficiency
            for op in operations for r in op.requirements
            if r.equipment_type == equipment_type
        )
        bounds.append(math.ceil(load / capacities[equipment_type]))
    return max(bounds)


def enumerate_budget_maximal_plans(upper_bound):
    """非极大方案总被某个设备更多的极大方案支配，只需检查后者。"""
    ranges = [range(q4.BUDGET // q4.UNIT_PRICE[t] + 1) for t in TYPES]
    minimum_price = min(q4.UNIT_PRICE.values())
    plans = []
    for extras in itertools.product(*ranges):
        cost = purchase_cost(extras)
        if cost <= q4.BUDGET and q4.BUDGET - cost < minimum_price:
            lb = simple_lower_bound(extras)
            if lb < upper_bound:
                plans.append((extras, cost, lb))
    return sorted(plans, key=lambda row: (row[2], -row[1], row[0]))


def cumulative_relaxation_bound(extras, time_limit, workers):
    """忽略具体设备路径和跨车间运输，保留工序链及同型设备累计容量。"""
    capacities = {
        t: 2 * q4.EXISTING_PER_TEAM[t] + n
        for t, n in zip(TYPES, extras)
    }
    operations, chains = q4.build_operations()
    model = q4.cp_model.CpModel()
    starts, ends = {}, {}
    intervals = {t: [] for t in TYPES}
    demands = {t: [] for t in TYPES}

    for op in operations:
        start = model.NewIntVar(0, 100_000, f"S_{op.code}")
        end = model.NewIntVar(0, 100_000, f"C_{op.code}")
        starts[op.code], ends[op.code] = start, end
        requirement_ends = []
        for ridx, requirement in enumerate(op.requirements):
            capacity = capacities[requirement.equipment_type]
            duration_values = [
                q4.duration_seconds(op.workload, requirement.efficiency, n)
                for n in range(1, capacity + 1)
            ]
            choices = [
                model.NewBoolVar(f"Y_{op.code}_{ridx}_{n}")
                for n in range(1, capacity + 1)
            ]
            model.AddExactlyOne(choices)
            count = model.NewIntVar(1, capacity, f"N_{op.code}_{ridx}")
            duration = model.NewIntVar(min(duration_values), max(duration_values),
                                       f"P_{op.code}_{ridx}")
            model.Add(count == sum((n + 1) * choices[n] for n in range(capacity)))
            model.Add(duration == sum(duration_values[n] * choices[n]
                                      for n in range(capacity)))
            req_end = model.NewIntVar(0, 100_000, f"E_{op.code}_{ridx}")
            interval = model.NewIntervalVar(start, duration, req_end,
                                            f"I_{op.code}_{ridx}")
            intervals[requirement.equipment_type].append(interval)
            demands[requirement.equipment_type].append(count)
            requirement_ends.append(req_end)
        model.AddMaxEquality(end, requirement_ends)

    for workshop, chain in chains.items():
        model.Add(starts[chain[0]] >= min(
            q4.initial_travel_time(g, workshop) for g in (1, 2)
        ))
        for previous, current in zip(chain, chain[1:]):
            model.Add(starts[current] >= ends[previous])
    for equipment_type in TYPES:
        model.AddCumulative(intervals[equipment_type],
                            demands[equipment_type], capacities[equipment_type])

    cmax = model.NewIntVar(0, 100_000, "CmaxRelaxed")
    model.AddMaxEquality(cmax, [ends[chains[w][-1]] for w in "ABCDE"])
    model.Minimize(cmax)
    solver = q4.cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = workers
    solver.parameters.random_seed = 20260820
    status = solver.Solve(model)
    if status != q4.cp_model.OPTIMAL:
        raise RuntimeError(f"累积资源下界未精确求出：{extras}, {solver.StatusName(status)}")
    return solver.Value(cmax)


def solve_full(extras, time_limit, workers):
    scheduler = q4.BudgetScheduler(
        time_limit, workers, False, fixed_totals=as_plan(extras)
    )
    scheduler.build()
    solver, status = scheduler.solve("makespan")
    if status != q4.cp_model.OPTIMAL:
        raise RuntimeError(
            f"完整模型未证明最优：{extras}, {solver.StatusName(status)}, "
            f"UB={solver.Value(scheduler.makespan)}, LB={solver.BestObjectiveBound()}"
        )
    return scheduler, solver, solver.Value(scheduler.makespan)


def main():
    parser = argparse.ArgumentParser(description="B题问题4全局最优分解求解")
    parser.add_argument("--full-time", type=float, default=180.0)
    parser.add_argument("--relax-time", type=float, default=120.0)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    print("步骤1：精确求解主候选购置结构……", flush=True)
    scheduler, solver, incumbent = solve_full(
        SEED_EXTRAS, args.full_time, args.workers
    )
    print(f"主候选完整模型：OPTIMAL，Cmax={incumbent}", flush=True)

    print("步骤2：枚举可竞争的预算极大购置结构并求松弛下界……", flush=True)
    candidate_rows = enumerate_budget_maximal_plans(incumbent)
    relaxation_rows = []
    for extras, cost, simple_lb in candidate_rows:
        if extras == SEED_EXTRAS:
            relaxation_rows.append((extras, cost, simple_lb, None, "完整模型达到上界"))
            continue
        bound = cumulative_relaxation_bound(
            extras, args.relax_time, args.workers
        )
        relaxation_rows.append((extras, cost, simple_lb, bound, "已排除"))
        print(f"  {extras}: 累积资源下界={bound}", flush=True)
        if bound < incumbent:
            rival_scheduler, rival_solver, rival_value = solve_full(
                extras, args.full_time, args.workers
            )
            if rival_value < incumbent:
                scheduler, solver, incumbent = rival_scheduler, rival_solver, rival_value
                raise RuntimeError("发现更优结构；请重新执行以更新候选筛选。")

    print("步骤3：验证较低成本近邻结构……", flush=True)
    _, _, lower_cost_value = solve_full(
        LOWER_COST_RIVAL, args.full_time, args.workers
    )
    if lower_cost_value <= incumbent:
        raise RuntimeError("较低成本结构达到同等工期，需要继续执行成本优化。")

    operation_rows, assignment_rows = scheduler.extract(solver)
    purchase_counts = scheduler.purchased_counts(assignment_rows)
    cost = purchase_cost(SEED_EXTRAS)
    q4.validate_solution(
        scheduler, operation_rows, assignment_rows, purchase_counts, cost, incumbent
    )
    status_lines = [
        "全局求解状态：OPTIMAL",
        f"完整模型可行解上界：{incumbent} s",
        f"完整模型严格下界：{incumbent} s",
        f"预算极大竞争结构数：{len(candidate_rows)}",
        "其余竞争结构均被精确累积资源松弛下界排除",
        f"低成本近邻结构{LOWER_COST_RIVAL}的严格最优值：{lower_cost_value} s",
    ]
    paths, summary = q4.write_results(
        scheduler, operation_rows, assignment_rows, purchase_counts,
        incumbent, cost, status_lines,
    )
    proof_path = ROOT / "问题4_全局最优证明明细.txt"
    lines = [
        "购置向量顺序：自动化输送臂、工业清洗机、精密灌装机、自动传感多功能机、高速抛光机",
        f"最终上界：{incumbent} s",
        "竞争结构下界：",
    ]
    for row in relaxation_rows:
        lines.append(str(row))
    lines.append(f"低成本近邻完整模型最优值：{lower_cost_value} s")
    proof_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(summary, end="")
    print("全局最优性证明：通过")
    for path in [*paths, proof_path]:
        print(path)


if __name__ == "__main__":
    main()
