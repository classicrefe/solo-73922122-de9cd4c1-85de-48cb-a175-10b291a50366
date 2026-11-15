"""networkx 最小替身：仅实现 solver 用到的 DiGraph / is_directed_acyclic_graph /
maximum_flow（Edmonds-Karp），用于无网络环境下本地测试。Docker 镜像内使用真正的 networkx。
"""
from collections import deque


class DiGraph:
    def __init__(self):
        self.adj = {}  # node -> {neighbor: {"capacity": int}}

    def add_node(self, n):
        self.adj.setdefault(n, {})

    def add_nodes_from(self, nodes):
        for n in nodes:
            self.add_node(n)

    def add_edge(self, u, v, capacity=None, **attrs):
        self.add_node(u)
        self.add_node(v)
        edge = dict(attrs)
        if capacity is not None:
            edge["capacity"] = capacity
        self.adj[u][v] = edge


def is_directed_acyclic_graph(g):
    indeg = {n: 0 for n in g.adj}
    for u in g.adj:
        for v in g.adj[u]:
            indeg[v] += 1
    queue = deque(n for n, d in indeg.items() if d == 0)
    seen = 0
    while queue:
        u = queue.popleft()
        seen += 1
        for v in g.adj[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                queue.append(v)
    return seen == len(indeg)


def maximum_flow(g, s, t):
    """Edmonds-Karp。返回 (流量值, {u: {v: flow}})。容量为整数时流量为整数。"""
    cap = {}
    for u in g.adj:
        for v, attrs in g.adj[u].items():
            cap[(u, v)] = cap.get((u, v), 0) + attrs.get("capacity", 0)

    neighbors = {}
    for u, v in cap:
        neighbors.setdefault(u, set()).add(v)
        neighbors.setdefault(v, set()).add(u)

    flow = {}
    total = 0
    while True:
        parent = {s: None}
        q = deque([s])
        while q and t not in parent:
            u = q.popleft()
            for v in neighbors.get(u, ()):
                if v in parent:
                    continue
                residual = cap.get((u, v), 0) - flow.get((u, v), 0) + flow.get((v, u), 0)
                if residual > 0:
                    parent[v] = u
                    q.append(v)
        if t not in parent:
            break
        inc = float("inf")
        v = t
        while v != s:
            u = parent[v]
            residual = cap.get((u, v), 0) - flow.get((u, v), 0) + flow.get((v, u), 0)
            inc = min(inc, residual)
            v = u
        v = t
        while v != s:
            u = parent[v]
            fwd_room = cap.get((u, v), 0) - flow.get((u, v), 0)
            use_fwd = min(fwd_room, inc)
            flow[(u, v)] = flow.get((u, v), 0) + use_fwd
            if use_fwd < inc:  # 剩余部分抵消反向流
                flow[(v, u)] = flow.get((v, u), 0) - (inc - use_fwd)
            v = u
        total += inc

    flow_dict = {}
    for (u, v), f in flow.items():
        if f:
            flow_dict.setdefault(u, {})[v] = f
    return total, flow_dict
