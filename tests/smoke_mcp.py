import asyncio, json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(
        command="py", args=["-3", "mcp_server.py"],
        cwd="E:/workspace/life-db")
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("TOOLS:", sorted(t.name for t in tools.tools))

            r1 = await s.call_tool("lifedb_stats", {})
            st = json.loads(r1.content[0].text)
            print("STATS:", st["schema_version"], "events=", st["events"],
                  "geo=", st["geo_points"], "span=", st["span"])

            r2 = await s.call_tool("lifedb_geo_track", {
                "start": "2026-08-24T00:00:00+08:00",
                "end": "2026-08-25T00:00:00+08:00", "limit": 100})
            trk = json.loads(r2.content[0].text)
            print("TRACK:", "total=", trk["total"], "returned=", trk["returned"],
                  "step=", trk["step"], "first=", trk["points"][0][:3])

            r3 = await s.call_tool("lifedb_export_atlas", {
                "start": "2026-08-24T00:00:00+08:00",
                "end": "2026-08-25T00:00:00+08:00",
                "modalities": "workout,health_metric", "max_points": 5000})
            at = json.loads(r3.content[0].text)
            print("ATLAS:", "events=", len(at["events"]), "photos=",
                  len(at["photos"]), "track_pts=", at["track"]["returned"])

            r4 = await s.call_tool("lifedb_around", {
                "ts": "2026-08-24T12:17:46+08:00", "window": "30m"})
            evs = json.loads(r4.content[0].text)
            print("AROUND:", len(evs), "events,",
                  sorted({e["modality"] for e in evs}))

            r5 = await s.call_tool("lifedb_ingest_jsonl", {
                "path": "E:/workspace/life-db/samples/demo.jsonl",
                "dry_run": True})
            print("INGEST(dry):", r5.content[0].text)

            r6 = await s.call_tool("lifedb_adapters", {})
            ads = json.loads(r6.content[0].text)
            print("ADAPTERS:", [a["name"] for a in ads])
            print("SMOKE OK")

asyncio.run(main())
