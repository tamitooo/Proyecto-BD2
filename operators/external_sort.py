"""External merge sort educativo (run generation + k-way merge)."""
from __future__ import annotations
import heapq, os, pickle, tempfile
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Optional

@dataclass
class ExternalSortStats:
    rows: int = 0
    initial_runs: int = 0
    merge_passes: int = 0
    temporary_files: int = 0

class ExternalSort:
    def __init__(self, memory_rows: int = 1024, fan_in: int = 8):
        if memory_rows < 2 or fan_in < 2:
            raise ValueError("memory_rows and fan_in must be >= 2")
        self.memory_rows = memory_rows
        self.fan_in = fan_in
        self.last_stats = ExternalSortStats()

    @staticmethod
    def _dump(path, rows):
        with open(path, "wb") as f:
            for row in rows: pickle.dump(row, f, protocol=pickle.HIGHEST_PROTOCOL)

    @staticmethod
    def _iter(path):
        with open(path, "rb") as f:
            while True:
                try: yield pickle.load(f)
                except EOFError: return

    def sort(self, rows: Iterable[Any], *, key: Callable[[Any], Any], descending: bool=False):
        rows = list(rows)
        stats = ExternalSortStats(rows=len(rows))
        if len(rows) <= self.memory_rows:
            self.last_stats = stats
            return sorted(rows, key=key, reverse=descending)
        with tempfile.TemporaryDirectory(prefix="bd2-sort-") as td:
            runs=[]
            for i in range(0,len(rows),self.memory_rows):
                chunk=sorted(rows[i:i+self.memory_rows],key=key,reverse=descending)
                p=os.path.join(td,f"run-{len(runs)}.bin"); self._dump(p,chunk); runs.append(p)
            stats.initial_runs=len(runs); stats.temporary_files += len(runs)
            while len(runs)>1:
                stats.merge_passes += 1; nxt=[]
                for pos in range(0,len(runs),self.fan_in):
                    batch=runs[pos:pos+self.fan_in]
                    iters=[iter(self._iter(p)) for p in batch]
                    heap=[]
                    for j,it in enumerate(iters):
                        try:
                            row=next(it); kval=key(row)
                            heapq.heappush(heap,(_Reverse(kval) if descending else kval,j,row))
                        except StopIteration: pass
                    merged=[]
                    while heap:
                        _,j,row=heapq.heappop(heap); merged.append(row)
                        try:
                            nr=next(iters[j]); kval=key(nr)
                            heapq.heappush(heap,(_Reverse(kval) if descending else kval,j,nr))
                        except StopIteration: pass
                    p=os.path.join(td,f"pass-{stats.merge_passes}-{len(nxt)}.bin"); self._dump(p,merged); nxt.append(p); stats.temporary_files += 1
                runs=nxt
            result=list(self._iter(runs[0]))
        self.last_stats=stats
        return result

class _Reverse:
    def __init__(self,value): self.value=value
    def __lt__(self,other): return self.value > other.value
    def __eq__(self,other): return self.value == other.value
