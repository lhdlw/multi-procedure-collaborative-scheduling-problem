"""问题3：双班组调度的贪心—模拟退火独立交叉验证。

本程序不调用 OR-Tools。它用优先序列编码、串行调度生成机制和模拟退火
独立搜索可行方案，用于从另一算法路线复核 CP-SAT 的 73575 s 结果。
启发式算法本身不承担最优性证明；最优性由精确模型的严格下界证明。
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
    team: int
    index: int
    available: int = 0
    location: Optional[str] = None


COUNTS_PER_TEAM = {
    "自动化输送臂": 4, "工业清洗机": 5, "精密灌装机": 5,
    "自动传感多功能机": 1, "高速抛光机": 1,
}
INITIAL_DISTANCE = {
    1: {"A": 400, "B": 620, "C": 460, "D": 710, "E": 400},
    2: {"A": 500, "B": 460, "C": 620, "D": 680, "E": 550},
}
PAIR_DISTANCE = {
    ("A", "B"): 1020, ("A", "C"): 1050, ("A", "D"): 900,
    ("A", "E"): 1400, ("B", "C"): 1100, ("B", "D"): 1630,
    ("B", "E"): 720, ("C", "D"): 520, ("C", "E"): 850,
    ("D", "E"): 1030,
}
EXACT_BENCHMARK = 73_575


def req(name: str, efficiency: int) -> Requirement:
    return Requirement(name, efficiency)


def build_operations() -> Tuple[Dict[str, Operation], Dict[str, List[str]]]:
    operations: Dict[str, Operation] = {}
    chains = {w: [] for w in "ABCDE"}

    def add(code: str, w: str, q: int, requirements: Sequence[Requirement]):
        operations[code] = Operation(code, w, q, tuple(requirements))
        chains[w].append(code)

    add("A1", "A", 300, [req("精密灌装机", 200), req("自动化输送臂", 250)])
    add("A2", "A", 500, [req("高速抛光机", 100), req("工业清洗机", 250)])
    add("A3", "A", 500, [req("自动传感多功能机", 100)])
    add("B1", "B", 120, [req("工业清洗机", 100)])
    add("B2", "B", 1500, [req("精密灌装机", 200), req("自动化输送臂", 300)])
    add("B3", "B", 360, [req("精密灌装机", 350)])
    add("B4", "B", 360, [req("高速抛光机", 120), req("自动传感多功能机", 100)])
    add("C1", "C", 720, [req("工业清洗机", 250), req("自动化输送臂", 250)])
    add("C2", "C", 720, [req("精密灌装机", 350)])
    for k in range(1, 4):
        add(f"C3-{k}", "C", 360, [req("精密灌装机", 200), req("自动化输送臂", 250)])
        add(f"C4-{k}", "C", 400, [req("高速抛光机", 120), req("工业清洗机", 100)])
        add(f"C5-{k}", "C", 400, [req("自动传感多功能机", 100)])
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


def duration(q: int, efficiency: int, count: int) -> int:
    return math.ceil(3600 * q / (efficiency * count))


def travel(machine: MachineState, destination: str) -> int:
    if machine.location is None:
        distance = INITIAL_DISTANCE[machine.team][destination]
    elif machine.location == destination:
        return 0
    else:
        distance = PAIR_DISTANCE[tuple(sorted((machine.location, destination)))]
    return math.ceil(distance / 2)


def arrival(machine: MachineState, destination: str) -> int:
    return machine.available + travel(machine, destination)


def fmt_time(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def decode(priority: Sequence[str], chains: Dict[str, List[str]]) -> List[str]:
    counters = {w: 0 for w in chains}
    result = []
    for w in priority:
        result.append(chains[w][counters[w]])
        counters[w] += 1
    return result


def build_machine_pool() -> Dict[str, List[MachineState]]:
    return {
        equipment_type: [MachineState(team, index)
                         for team in (1, 2) for index in range(1, count + 1)]
        for equipment_type, count in COUNTS_PER_TEAM.items()
    }


def schedule(priority, operations, chains, keep_details=False):
    """串行调度生成：枚举每类设备投入台数并选择最早到达的具体设备。"""
    machines = build_machine_pool()
    workshop_ready = {w: 0 for w in chains}
    rows = []

    for code in decode(priority, chains):
        op = operations[code]
        option_lists = []
        for requirement in op.requirements:
            states = machines[requirement.equipment_type]
            order = sorted(range(len(states)),
                           key=lambda i: (arrival(states[i], op.workshop),
                                          states[i].team, states[i].index))
            options = []
            for count in range(1, len(states) + 1):
                chosen = tuple(order[:count])
                ready = max(arrival(states[i], op.workshop) for i in chosen)
                options.append((requirement, chosen, ready,
                                duration(op.workload, requirement.efficiency, count)))
            option_lists.append(options)

        combinations = [(x,) for x in option_lists[0]]
        for options in option_lists[1:]:
            combinations = [a + (b,) for a in combinations for b in options]

        best, best_key = None, None
        for combination in combinations:
            start = max([workshop_ready[op.workshop]] + [x[2] for x in combination])
            end = start + max(x[3] for x in combination)
            # 首先最早结束；同值时优先较早开始、较少设备和较少总到达时刻。
            key = (end, start, sum(len(x[1]) for x in combination),
                   sum(x[2] for x in combination))
            if best_key is None or key < best_key:
                best, best_key = combination, key

        start = max([workshop_ready[op.workshop]] + [x[2] for x in best])
        end = start + max(x[3] for x in best)
        workshop_ready[op.workshop] = end
        allocations = []
        for requirement, chosen, _ready, work_time in best:
            states = machines[requirement.equipment_type]
            for i in chosen:
                states[i].available = start + work_time
                states[i].location = op.workshop
            allocations.append(f"{requirement.equipment_type}×{len(chosen)}")
        if keep_details:
            rows.append((op.workshop, code, start, end, "、".join(allocations)))
    return max(workshop_ready.values()), workshop_ready, rows


def remaining_work(operations, chains):
    values = {}
    for w, chain in chains.items():
        running = 0
        for code in reversed(chain):
            op = operations[code]
            running += max(duration(op.workload, r.efficiency,
                                    2 * COUNTS_PER_TEAM[r.equipment_type])
                           for r in op.requirements)
            values[code] = running
    return values


def initial_priority(operations, chains):
    remaining = remaining_work(operations, chains)
    position = {w: 0 for w in chains}
    result = []
    while len(result) < len(operations):
        candidates = [w for w in chains if position[w] < len(chains[w])]
        w = max(candidates, key=lambda z: remaining[chains[z][position[z]]])
        result.append(w)
        position[w] += 1
    return result


def neighbor(priority, rng):
    x = list(priority)
    for _ in range(30):
        i, j = sorted(rng.sample(range(len(x)), 2))
        if x[i] != x[j]:
            x[i], x[j] = x[j], x[i]
            return x
    return x


def anneal(operations, chains, iterations, restarts, seed):
    rng = random.Random(seed)
    base = initial_priority(operations, chains)
    global_best, global_value = list(base), schedule(base, operations, chains)[0]
    initial_value = global_value
    for restart in range(restarts):
        current = list(global_best if restart else base)
        for _ in range(6 * restart):
            current = neighbor(current, rng)
        current_value = schedule(current, operations, chains)[0]
        temperature = 5000.0
        cooling = math.exp(math.log(0.25 / temperature) / max(1, iterations))
        for _ in range(iterations):
            candidate = neighbor(current, rng)
            value = schedule(candidate, operations, chains)[0]
            delta = value - current_value
            if delta <= 0 or rng.random() < math.exp(-delta / max(temperature, 1e-9)):
                current, current_value = candidate, value
            if current_value < global_value:
                global_best, global_value = list(current), current_value
            if global_value <= EXACT_BENCHMARK:
                return global_best, global_value, initial_value
            temperature *= cooling
    return global_best, global_value, initial_value


def main():
    parser = argparse.ArgumentParser(description="问题3模拟退火独立交叉验证")
    parser.add_argument("--iterations", type=int, default=100000)
    parser.add_argument("--restarts", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260820)
    args = parser.parse_args()
    operations, chains = build_operations()
    priority, value, initial = anneal(operations, chains, args.iterations,
                                      args.restarts, args.seed)
    makespan, workshop_ready, rows = schedule(priority, operations, chains, True)
    print("问题3：贪心—模拟退火独立交叉验证")
    print("=" * 62)
    print(f"贪心初解：          {initial} s（{fmt_time(initial)}）")
    print(f"模拟退火最好结果：  {makespan} s（{fmt_time(makespan)}）")
    print(f"CP-SAT全局最优值： {EXACT_BENCHMARK} s（{fmt_time(EXACT_BENCHMARK)}）")
    print("交叉验证：" + ("达到相同结果，通过" if makespan == EXACT_BENCHMARK
                         else "本次启发式搜索尚未达到精确最优值"))
    print("各车间完成时间：")
    for w in "ABCDE":
        print(f"  {w}: {workshop_ready[w]} s（{fmt_time(workshop_ready[w])}）")
    print("工序级方案：")
    for w, code, start, end, allocation in sorted(rows, key=lambda x: (x[2], x[0])):
        print(f"{w:<2} {code:<6} {fmt_time(start)}—{fmt_time(end)}  {allocation}")


if __name__ == "__main__":
    main()
