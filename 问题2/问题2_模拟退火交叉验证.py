"""B题问题2：贪心初解 + 模拟退火的独立交叉验证程序。

说明
----
1. 本程序不调用 OR-Tools，不依赖精确模型的求解过程；
2. 解编码为五条车间工序链的可行交织序列；
3. 给定序列后，以串行调度生成机制（SGS）安排具体设备、并联台数、
   跨车间运输和工序起止时间；
4. 模拟退火通过交换不同车间的两个位置搜索更优序列；
5. 仅在控制台打印结果，不生成 Excel 或 CSV 文件。

推荐运行：
    python 问题2_模拟退火交叉验证.py
快速演示：
    python 问题2_模拟退火交叉验证.py --iterations 30000
"""

from __future__ import annotations

import argparse
import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Requirement:
    equipment_type: str
    efficiency: int


@dataclass(frozen=True)
class Operation:
    code: str
    workshop: str
    workload: int
    requirements: Tuple[Requirement, ...]


@dataclass
class MachineState:
    available: int = 0
    location: Optional[str] = None


EQUIPMENT_COUNTS: Dict[str, int] = {
    "自动化输送臂": 4,
    "工业清洗机": 5,
    "精密灌装机": 5,
    "自动传感多功能机": 1,
    "高速抛光机": 1,
}

INITIAL_DISTANCE = {"A": 400, "B": 620, "C": 460, "D": 710, "E": 400}
PAIR_DISTANCE = {
    ("A", "B"): 1020,
    ("A", "C"): 1050,
    ("A", "D"): 900,
    ("A", "E"): 1400,
    ("B", "C"): 1100,
    ("B", "D"): 1630,
    ("B", "E"): 720,
    ("C", "D"): 520,
    ("C", "E"): 850,
    ("D", "E"): 1030,
}
MOVING_SPEED = 2
EXACT_BENCHMARK = 144_880


def req(name: str, efficiency: int) -> Requirement:
    return Requirement(name, efficiency)


def build_operations() -> Tuple[Dict[str, Operation], Dict[str, List[str]]]:
    operations: Dict[str, Operation] = {}
    chains: Dict[str, List[str]] = {w: [] for w in "ABCDE"}

    def add(code: str, workshop: str, workload: int, requirements: Sequence[Requirement]):
        operations[code] = Operation(code, workshop, workload, tuple(requirements))
        chains[workshop].append(code)

    add("A1", "A", 300, [req("精密灌装机", 200), req("自动化输送臂", 250)])
    add("A2", "A", 500, [req("高速抛光机", 100), req("工业清洗机", 250)])
    add("A3", "A", 500, [req("自动传感多功能机", 100)])
    add("B1", "B", 120, [req("工业清洗机", 100)])
    add("B2", "B", 1500, [req("精密灌装机", 200), req("自动化输送臂", 300)])
    add("B3", "B", 360, [req("精密灌装机", 350)])
    add("B4", "B", 360, [req("高速抛光机", 120), req("自动传感多功能机", 100)])
    add("C1", "C", 720, [req("工业清洗机", 250), req("自动化输送臂", 250)])
    add("C2", "C", 720, [req("精密灌装机", 350)])
    for cycle in range(1, 4):
        add(f"C3-{cycle}", "C", 360, [req("精密灌装机", 200), req("自动化输送臂", 250)])
        add(f"C4-{cycle}", "C", 400, [req("高速抛光机", 120), req("工业清洗机", 100)])
        add(f"C5-{cycle}", "C", 400, [req("自动传感多功能机", 100)])
    add("D1", "D", 600, [req("工业清洗机", 250)])
    add("D2", "D", 800, [req("精密灌装机", 200), req("自动化输送臂", 300)])
    add("D3", "D", 450, [req("精密灌装机", 350)])
    add("D4", "D", 1500, [req("高速抛光机", 120), req("自动传感多功能机", 300)])
    add("D5", "D", 1500, [req("自动传感多功能机", 300)])
    add("D6", "D", 700, [req("高速抛光机", 100)])
    add("E1", "E", 1000, [req("工业清洗机", 250)])
    add("E2", "E", 600, [req("精密灌装机", 350)])
    add("E3", "E", 600, [req("自动传感多功能机", 300), req("工业清洗机", 100)])
    return operations, chains


def travel_time(origin: Optional[str], destination: str) -> int:
    if origin is None:
        distance = INITIAL_DISTANCE[destination]
    elif origin == destination:
        return 0
    else:
        distance = PAIR_DISTANCE[tuple(sorted((origin, destination)))]
    return math.ceil(distance / MOVING_SPEED)


def duration_seconds(workload: int, efficiency: int, count: int) -> int:
    return math.ceil(workload * 3600 / (efficiency * count))


def fmt_time(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def decode(priority: Sequence[str], chains: Dict[str, List[str]]) -> List[str]:
    """把车间字母序列还原为满足各车间工艺顺序的工序序列。"""
    counters = {w: 0 for w in chains}
    result = []
    for workshop in priority:
        result.append(chains[workshop][counters[workshop]])
        counters[workshop] += 1
    return result


def machine_arrival(state: MachineState, workshop: str) -> int:
    return state.available + travel_time(state.location, workshop)


def schedule_from_priority(
    priority: Sequence[str],
    operations: Dict[str, Operation],
    chains: Dict[str, List[str]],
    keep_details: bool = False,
):
    """串行调度生成机制：按优先序列将任务追加到具体设备路径末端。"""
    machines = {
        equipment_type: [MachineState() for _ in range(count)]
        for equipment_type, count in EQUIPMENT_COUNTS.items()
    }
    workshop_ready = {w: 0 for w in chains}
    rows = []

    for code in decode(priority, chains):
        op = operations[code]
        base_start = workshop_ready[op.workshop]

        # 每类设备按“最早可到达该车间”排序；枚举投入台数的组合。
        ranked = {}
        for requirement in op.requirements:
            states = machines[requirement.equipment_type]
            ranked[requirement.equipment_type] = sorted(
                range(len(states)),
                key=lambda m: (machine_arrival(states[m], op.workshop), m),
            )

        choices: List[Tuple[Requirement, int, Tuple[int, ...], int, int]] = []
        for requirement in op.requirements:
            equipment_type = requirement.equipment_type
            order = ranked[equipment_type]
            options = []
            for count in range(1, len(order) + 1):
                selected = tuple(order[:count])
                ready = max(
                    machine_arrival(machines[equipment_type][m], op.workshop)
                    for m in selected
                )
                duration = duration_seconds(op.workload, requirement.efficiency, count)
                options.append((requirement, count, selected, ready, duration))
            choices.append(options)

        combinations = [(choice,) for choice in choices[0]]
        for options in choices[1:]:
            combinations = [old + (choice,) for old in combinations for choice in options]

        best = None
        best_key = None
        for combination in combinations:
            start = max([base_start] + [choice[3] for choice in combination])
            end = start + max(choice[4] for choice in combination)
            total_count = sum(choice[1] for choice in combination)
            total_arrival = sum(choice[3] for choice in combination)
            key = (end, start, total_count, total_arrival)
            if best_key is None or key < best_key:
                best_key = key
                best = combination

        assert best is not None
        start = max([base_start] + [choice[3] for choice in best])
        end = start + max(choice[4] for choice in best)
        workshop_ready[op.workshop] = end

        allocation = []
        for requirement, count, selected, _, duration in best:
            equipment_type = requirement.equipment_type
            for machine in selected:
                state = machines[equipment_type][machine]
                state.available = start + duration
                state.location = op.workshop
            allocation.append(f"{equipment_type}×{count}")

        if keep_details:
            rows.append((op.workshop, code, start, end, "、".join(allocation)))

    makespan = max(workshop_ready.values())
    compactness = sum(row[3] for row in rows) if keep_details else sum(workshop_ready.values())
    return makespan, compactness, workshop_ready, rows


def greedy_initial(operations: Dict[str, Operation], chains: Dict[str, List[str]]) -> List[str]:
    """利用剩余关键链长度规则构造初始可行交织序列。"""
    minimum_duration = {}
    for code, op in operations.items():
        minimum_duration[code] = max(
            duration_seconds(op.workload, r.efficiency, EQUIPMENT_COUNTS[r.equipment_type])
            for r in op.requirements
        )
    remaining = {}
    for workshop, chain in chains.items():
        running = 0
        for code in reversed(chain):
            running += minimum_duration[code]
            remaining[code] = running

    index = {w: 0 for w in chains}
    result = []
    while len(result) < len(operations):
        available = [w for w in chains if index[w] < len(chains[w])]
        chosen = max(
            available,
            key=lambda w: (remaining[chains[w][index[w]]], -ord(w)),
        )
        result.append(chosen)
        index[chosen] += 1
    return result


def random_neighbor(priority: Sequence[str], rng: random.Random) -> List[str]:
    neighbor = list(priority)
    n = len(neighbor)
    for _ in range(20):
        i, j = sorted(rng.sample(range(n), 2))
        if neighbor[i] != neighbor[j]:
            neighbor[i], neighbor[j] = neighbor[j], neighbor[i]
            return neighbor
    return neighbor


def simulated_annealing(
    operations: Dict[str, Operation],
    chains: Dict[str, List[str]],
    iterations: int,
    restarts: int,
    seed: int,
):
    rng = random.Random(seed)
    base = greedy_initial(operations, chains)
    global_best = None
    global_best_value = 10**18
    history = []

    for restart in range(restarts):
        current = list(base)
        if restart:
            for _ in range(10 * restart):
                current = random_neighbor(current, rng)
        current_value = schedule_from_priority(current, operations, chains)[0]
        best = list(current)
        best_value = current_value
        temperature = 8000.0
        cooling = math.exp(math.log(0.5 / temperature) / max(1, iterations))

        for iteration in range(iterations):
            candidate = random_neighbor(current, rng)
            candidate_value = schedule_from_priority(candidate, operations, chains)[0]
            delta = candidate_value - current_value
            if delta <= 0 or rng.random() < math.exp(-delta / max(temperature, 1e-9)):
                current = candidate
                current_value = candidate_value
            if current_value < best_value:
                best = list(current)
                best_value = current_value
            if best_value < global_best_value:
                global_best = list(best)
                global_best_value = best_value
            if iteration % max(1, iterations // 20) == 0:
                history.append((restart + 1, iteration, global_best_value))
            if global_best_value <= EXACT_BENCHMARK:
                return global_best, global_best_value, history
            temperature *= cooling

        # 路径重连：下一次从当前全局最好序列附近重新升温。
        if global_best is not None:
            base = list(global_best)

    assert global_best is not None
    return global_best, global_best_value, history


def main() -> None:
    parser = argparse.ArgumentParser(description="问题2模拟退火独立交叉验证")
    parser.add_argument("--iterations", type=int, default=120000, help="每次退火迭代次数")
    parser.add_argument("--restarts", type=int, default=8, help="重新升温次数")
    parser.add_argument("--seed", type=int, default=20260820, help="随机种子")
    args = parser.parse_args()

    operations, chains = build_operations()
    priority, best_value, _ = simulated_annealing(
        operations, chains, args.iterations, args.restarts, args.seed
    )
    makespan, _, workshop_ready, rows = schedule_from_priority(
        priority, operations, chains, keep_details=True
    )

    print("\n问题2：贪心—模拟退火交叉验证")
    print("=" * 58)
    print(f"模拟退火最好总工期：{makespan} s（{fmt_time(makespan)}）")
    print(f"精确模型最优值：    {EXACT_BENCHMARK} s（{fmt_time(EXACT_BENCHMARK)}）")
    print(f"交叉验证结果：{'一致，通过' if makespan == EXACT_BENCHMARK else '尚未达到精确最优值'}")
    print("\n各车间完成时间：")
    for workshop in "ABCDE":
        print(f"  {workshop}车间：{workshop_ready[workshop]:6d} s（{fmt_time(workshop_ready[workshop])}）")
    print("\n工序调度结果：")
    print(f"{'车间':<4}{'工序':<8}{'开始':>10}{'结束':>10}  设备配置")
    for workshop, code, start, end, allocation in sorted(rows, key=lambda r: (r[2], r[0], r[1])):
        print(f"{workshop:<6}{code:<10}{fmt_time(start):>10}{fmt_time(end):>10}  {allocation}")


if __name__ == "__main__":
    main()
