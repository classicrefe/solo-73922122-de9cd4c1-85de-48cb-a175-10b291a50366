"""管网流量守恒可行性核查核心逻辑。

约束模型：
- 管网为 2~8 个节点、至多 12 条管段的有向无环网络；
- 进水点（源）自由供水，出水点（汇）自由受水；
- 其余内部节点流入量 == 流出量；
- 每条管段读数为其闭区间 [下限, 上限] 内的整数。

求解方法（下界消去 + 最大流，NetworkX 实现）：
对每条管段 u->v（区间 [lo, hi]）：
  1. 容量改为 hi - lo，并把下界 lo 转化为节点供需：
     u 的供需 -= lo，v 的供需 += lo；
  2. 为避免平行管段冲突，每条管段经中间节点拆分：u -> mid -> v；
  3. 增加超级源 SS、超级汇 TT：供需为正的节点从 SS 接入相应容量，
     供需为负的节点向 TT 接出相应容量；
  4. 增加出水点 -> 进水点、容量无穷大的回流边，把问题化为循环流。
若 SS 发出的所有边均满流，则原问题可行；管段读数 = lo + 该段拆分边上的流量。
容量全为整数，最大流解必为整数，故读数天然为整数。
"""
from __future__ import annotations

import re

import networkx as nx

MIN_NODES = 2
MAX_NODES = 8
MAX_PIPES = 12

_INT_RE = re.compile(r"^\d+$")

# 内部哨兵节点用元组表示，不会与 CSV 中的字符串节点名冲突
_SS = ("__super_source__",)
_TT = ("__super_sink__",)


class InputError(Exception):
    """CSV 内容、区间或拓扑不合法（消息面向数据质量员，直接展示）。"""


_HEADER_ALIASES = {
    "id": {"id", "pipe", "pipe_id", "no", "编号", "管段", "管段编号"},
    "start": {"from", "start", "u", "起点", "起始点", "上游", "上游节点"},
    "end": {"to", "end", "v", "终点", "结束点", "下游", "下游节点"},
    "lower": {"lower", "lo", "min", "下限", "流量下限", "最小流量"},
    "upper": {"upper", "hi", "max", "上限", "流量上限", "最大流量"},
}


def _split_rows(text: str) -> list[list[str]]:
    rows = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        rows.append([cell.strip() for cell in line.split(",")])
    return rows


def parse_csv(text: str) -> list[dict]:
    """把 CSV 文本解析为管段列表，非法内容抛 InputError。"""
    rows = _split_rows(text)
    if not rows:
        raise InputError("CSV 为空：请提供管段数据。")

    alias_union = set().union(*_HEADER_ALIASES.values())
    first = [c.lower() for c in rows[0]]
    if any(c in alias_union for c in first):
        # 有表头：按别名定位五列
        col = {}
        for field, aliases in _HEADER_ALIASES.items():
            hits = [i for i, h in enumerate(first) if h in aliases]
            if len(hits) != 1:
                raise InputError(
                    f"表头缺少或重复「{field}」列（可用别名：{'、'.join(sorted(aliases))}）。"
                )
            col[field] = hits[0]
        width = len(rows[0])
        data_rows = rows[1:]
        first_lineno = 2
    else:
        # 无表头：固定顺序 编号,起点,终点,下限,上限
        if len(rows[0]) != 5:
            raise InputError(
                "未识别到表头时，每行须依次为：管段编号,起点,终点,流量下限,流量上限（共 5 列）。"
            )
        col = {"id": 0, "start": 1, "end": 2, "lower": 3, "upper": 4}
        width = 5
        data_rows = rows
        first_lineno = 1

    pipes: list[dict] = []
    seen_ids: set[str] = set()
    for idx, row in enumerate(data_rows):
        lineno = first_lineno + idx
        if len(row) != width:
            raise InputError(f"第 {lineno} 行列数与表头不一致。")
        pid, u, v = row[col["id"]], row[col["start"]], row[col["end"]]
        lo_s, hi_s = row[col["lower"]], row[col["upper"]]
        if not pid:
            raise InputError(f"第 {lineno} 行：管段编号不能为空。")
        if pid in seen_ids:
            raise InputError(f"第 {lineno} 行：管段编号「{pid}」重复。")
        seen_ids.add(pid)
        if not u or not v:
            raise InputError(f"第 {lineno} 行：起点、终点不能为空。")
        if not _INT_RE.match(lo_s) or not _INT_RE.match(hi_s):
            raise InputError(
                f"第 {lineno} 行：流量上下界必须为非负整数（收到 {lo_s!r}、{hi_s!r}）。"
            )
        lo, hi = int(lo_s), int(hi_s)
        if lo > hi:
            raise InputError(
                f"第 {lineno} 行：管段 {pid} 下限 {lo} 大于上限 {hi}，区间非法。"
            )
        if u == v:
            raise InputError(f"第 {lineno} 行：管段 {pid} 起点与终点相同（自环）。")
        pipes.append({"id": pid, "start": u, "end": v, "lower": lo, "upper": hi})
    return pipes


def _validate(pipes: list[dict], source: str, sink: str) -> list[str]:
    """校验规模与拓扑，返回节点列表；不合法抛 InputError。"""
    if not pipes:
        raise InputError("至少需要 1 条管段。")
    if len(pipes) > MAX_PIPES:
        raise InputError(f"管段数 {len(pipes)} 条，超过上限 {MAX_PIPES} 条。")

    for p in pipes:
        lo, hi = p["lower"], p["upper"]
        if not (isinstance(lo, int) and isinstance(hi, int)) or lo < 0 or hi < 0:
            raise InputError(f"管段 {p['id']} 的流量上下界必须为非负整数。")
        if lo > hi:
            raise InputError(f"管段 {p['id']} 下限 {lo} 大于上限 {hi}，区间非法。")

    nodes = sorted({p["start"] for p in pipes} | {p["end"] for p in pipes})
    if not (MIN_NODES <= len(nodes) <= MAX_NODES):
        raise InputError(f"节点数为 {len(nodes)} 个，须在 {MIN_NODES}～{MAX_NODES} 之间。")

    if not source or not sink:
        raise InputError("请指定进水点与出水点。")
    if source == sink:
        raise InputError("进水点与出水点不能相同。")
    missing = [n for n in (source, sink) if n not in nodes]
    if missing:
        raise InputError(f"进水/出水点 {missing} 未出现在管段数据中。")

    graph = nx.DiGraph()
    graph.add_nodes_from(nodes)
    for p in pipes:
        graph.add_edge(p["start"], p["end"])
    if not nx.is_directed_acyclic_graph(graph):
        raise InputError("拓扑错误：管网存在有向环，须为从进水点到出水点的有向无环网络。")

    # 所有节点须自进水点可达、且能到达出水点
    adj = {n: [] for n in nodes}
    radj = {n: [] for n in nodes}
    for p in pipes:
        adj[p["start"]].append(p["end"])
        radj[p["end"]].append(p["start"])

    def reach(start: str, arcs: dict) -> set:
        seen, stack = set(), [start]
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            stack.extend(arcs[x])
        return seen

    from_src = reach(source, adj)
    to_sink = reach(sink, radj)
    stray = [n for n in nodes if n not in from_src or n not in to_sink]
    if stray:
        raise InputError(
            f"拓扑错误：节点 {stray} 不在进水点「{source}」到出水点「{sink}」的通路上。"
        )
    return nodes


def solve(pipes: list[dict], source: str, sink: str) -> dict:
    """核查可行性。返回 {feasible, flows, total_supply, message}；输入非法抛 InputError。"""
    nodes = _validate(pipes, source, sink)

    big = sum(p["upper"] for p in pipes) + 1  # “无穷大”容量
    flow_net = nx.DiGraph()
    balance = {n: 0 for n in nodes}  # 正值=需要净流入，负值=需要净流出

    for i, p in enumerate(pipes):
        mid = ("__pipe__", i)  # 拆分中间节点，天然支持平行管段
        flow_net.add_edge(p["start"], mid, capacity=p["upper"] - p["lower"])
        flow_net.add_edge(mid, p["end"], capacity=big)
        balance[p["start"]] -= p["lower"]
        balance[p["end"]] += p["lower"]

    demand = 0
    for n, b in balance.items():
        if b > 0:
            flow_net.add_edge(_SS, n, capacity=b)
            demand += b
        elif b < 0:
            flow_net.add_edge(n, _TT, capacity=-b)
    flow_net.add_edge(sink, source, capacity=big)  # 回流边：化为循环流

    value, flow = nx.maximum_flow(flow_net, _SS, _TT)
    if value != demand:
        return {
            "feasible": False,
            "flows": None,
            "total_supply": None,
            "message": "不存在同时满足各管段区间与内部节点守恒的整数流量分配。",
        }

    flows = []
    for i, p in enumerate(pipes):
        mid = ("__pipe__", i)
        extra = int(flow.get(p["start"], {}).get(mid, 0))
        flows.append({**p, "value": p["lower"] + extra})
    total_supply = sum(f["value"] for f in flows if f["start"] == source) - sum(
        f["value"] for f in flows if f["end"] == source
    )
    return {
        "feasible": True,
        "flows": flows,
        "total_supply": total_supply,
        "message": "可行：以下为一组满足全部约束的逐段整数读数，可供复核。",
    }
