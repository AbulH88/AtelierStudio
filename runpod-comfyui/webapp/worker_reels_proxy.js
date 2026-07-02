export default {
  async fetch(request, env) {
    if (request.headers.get("x-auth") !== env.AUTH_SECRET)
      return new Response("unauthorized", { status: 401 });
    const url = new URL(request.url);
    const key = decodeURIComponent(url.pathname.replace(/^\//, ""));
    const m = request.method;
    if (m === "GET" && url.searchParams.has("list")) {
      const prefix = url.searchParams.get("prefix") || "";
      const delimiter = url.searchParams.get("delimiter") || undefined;
      const out = await env.BUCKET.list({ prefix, delimiter });
      return Response.json({
        objects: out.objects.map(o => ({ key: o.key, size: o.size })),
        prefixes: out.delimitedPrefixes || []
      });
    }
    if (m === "GET") {
      const rangeHeader = request.headers.get("range");
      let range;
      if (rangeHeader) {
        const match = /^bytes=(\d*)-(\d*)$/.exec(rangeHeader.trim());
        if (match) {
          const [, startStr, endStr] = match;
          if (startStr === "" && endStr !== "") {
            range = { suffix: parseInt(endStr, 10) };
          } else if (endStr === "") {
            range = { offset: parseInt(startStr, 10) };
          } else {
            const start = parseInt(startStr, 10);
            const end = parseInt(endStr, 10);
            range = { offset: start, length: end - start + 1 };
          }
        }
      }
      const obj = await env.BUCKET.get(key, range ? { range } : {});
      if (!obj) return new Response("not found", { status: 404 });
      const h = new Headers();
      obj.writeHttpMetadata(h);
      h.set("Accept-Ranges", "bytes");
      h.set("etag", obj.httpEtag);
      if (url.searchParams.has("download"))
        h.set("Content-Disposition", `attachment; filename="${key.split("/").pop()}"`);
      if (range) {
        const start = obj.range.offset ?? 0;
        const length = obj.range.length ?? (obj.size - start);
        const end = start + length - 1;
        h.set("Content-Range", `bytes ${start}-${end}/${obj.size}`);
        h.set("Content-Length", String(length));
        return new Response(obj.body, { status: 206, headers: h });
      }
      return new Response(obj.body, { headers: h });
    }
    if (m === "PUT") { await env.BUCKET.put(key, request.body); return new Response("ok"); }
    if (m === "DELETE") { await env.BUCKET.delete(key); return new Response("ok"); }
    return new Response("method not allowed", { status: 405 });
  }
};
