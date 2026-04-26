"""Muestra las memorias de todos los perfiles."""
import memory as mem
from profiles import PROFILES

for key, profile in PROFILES.items():
    m = mem.load(key)
    summaries = m.get("summaries", [])
    entries = m.get("entries", [])
    cycles = m.get("cycles_reflected", 0)

    print(f"\n{'='*60}")
    print(f"  {profile['name'].upper()} | {len(entries)} entradas | {len(summaries)} summaries | {cycles} ciclos reflejados")
    print(f"{'='*60}")

    if summaries:
        print("\n  CORE LESSONS:")
        for s in summaries:
            print(f"    • {s}")

    if entries:
        print(f"\n  ENTRADAS RECIENTES ({len(entries)}):")
        for e in entries[-20:]:
            stars = "★" * e.get("importance", 2)
            pnl_str = f" | pnl={e['pnl_pct']:+.1f}%" if "pnl_pct" in e else ""
            print(f"\n    [cycle#{e['cycle']} | {e['category']} {stars}{pnl_str}]")
            print(f"    {e['content']}")
    else:
        print("\n  (sin entradas aún)")

print()
