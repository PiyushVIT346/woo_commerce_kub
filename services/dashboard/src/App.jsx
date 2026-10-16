import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

const fmt = (d) => (d ? new Date(d).toLocaleString() : "—");
const Badge = ({ s }) => <span className={`badge ${s}`}>{({ connected: "Connected", unreachable: "Unreachable", disabled: "Disabled" })[s] || s}</span>;

function usePoll(path, ms = 0) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api(path).then((d) => { setData(d); setError(""); }).catch((e) => setError(e.message)), [path]);
  useEffect(() => { load(); if (!ms) return; const t = setInterval(load, ms); return () => clearInterval(t); }, [load, ms]);
  return [data, load, error];
}

function Login() {
  const [f, setF] = useState({ email: "", password: "" });
  const [err, setErr] = useState("");
  const go = async (e) => { e.preventDefault(); try { await api("/auth/login", { method: "POST", body: f }); location.reload(); } catch (x) { setErr(x.message); } };
  return (
    <form className="card login" onSubmit={go}>
      <h2>Sign in</h2>
      <div className="row"><input style={{ flex: 1 }} placeholder="Email" autoComplete="username" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></div>
      <div className="row"><input style={{ flex: 1 }} type="password" placeholder="Password" autoComplete="current-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></div>
      {err && <p className="err">{err}</p>}
      <button className="btn primary">Sign in</button>
    </form>
  );
}

function Accept({ token }) {
  const [f, setF] = useState({ name: "", password: "" });
  const [msg, setMsg] = useState("");
  const go = async (e) => {
    e.preventDefault();
    try { await api("/auth/accept-invite", { method: "POST", body: { ...f, token } }); location.href = "/"; } catch (x) { setMsg(x.message); }
  };
  return (
    <form className="card login" onSubmit={go}>
      <h2>Join the team</h2>
      <div className="row"><input style={{ flex: 1 }} placeholder="Your name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></div>
      <div className="row"><input style={{ flex: 1 }} type="password" placeholder="Choose a password (8+ characters)" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></div>
      {msg && <p className="err">{msg}</p>}
      <button className="btn primary">Create account</button>
    </form>
  );
}

const empty = { slug: "", name: "", url: "", auth_type: "none", header_name: "", secret: "" };
function Servers({ me }) {
  const [list, load, error] = usePoll("/servers", 5000);
  const [form, setForm] = useState(null); // null | {id?, ...}
  const [err, setErr] = useState("");
  const isAdmin = me.role === "admin";
  const act = async (fn) => { setErr(""); try { await fn(); await load(); } catch (e) { setErr(e.message); } };
  const save = (e) => {
    e.preventDefault();
    act(async () => {
      const { id, ...b } = form;
      if (id) { if (!b.secret) delete b.secret; await api(`/servers/${id}`, { method: "PATCH", body: b }); }
      else await api("/servers", { method: "POST", body: b });
      setForm(null);
    });
  };
  return (
    <>
      <h2>MCP servers</h2>
      {(error || err) && <p className="err">{error || err}</p>}
      {isAdmin && !form && <div className="row"><button className="btn primary" onClick={() => setForm({ ...empty })}>Add server</button></div>}
      {form && (
        <form className="card" onSubmit={save}>
          <h3 style={{ marginTop: 0 }}>{form.id ? `Edit ${form.slug}` : "Add server"}</h3>
          <div className="row">
            <input placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            {!form.id && <input placeholder="slug (e.g. github)" value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} />}
            <input style={{ flex: 1, minWidth: 260 }} placeholder="https://host/mcp" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
          </div>
          <div className="row">
            <select value={form.auth_type} onChange={(e) => setForm({ ...form, auth_type: e.target.value })}>
              <option value="none">No credential</option><option value="bearer">Bearer token</option><option value="header">Custom header</option>
            </select>
            {form.auth_type === "header" && <input placeholder="Header name" value={form.header_name || ""} onChange={(e) => setForm({ ...form, header_name: e.target.value })} />}
            {form.auth_type !== "none" && <input type="password" placeholder={form.id ? "Credential (blank = keep current)" : "Credential"} value={form.secret} onChange={(e) => setForm({ ...form, secret: e.target.value })} />}
          </div>
          <div className="row"><button className="btn primary">Save</button><button type="button" className="btn" onClick={() => setForm(null)}>Cancel</button></div>
          <p className="muted">Credentials are encrypted on the server and never shown again.</p>
        </form>
      )}
      <div className="card">
        <table>
          <thead><tr><th>Server</th><th>Status</th><th>Tools</th>{isAdmin && <th></th>}</tr></thead>
          <tbody>
            {(list || []).map((s) => (
              <tr key={s.id}>
                <td><b>{s.name}</b><div className="muted">{s.slug}{isAdmin && ` · ${s.url}`}</div></td>
                <td><Badge s={s.status} />{s.last_error && s.status === "unreachable" && <div className="muted">{s.last_error}</div>}<div className="muted">checked {fmt(s.last_checked_at)}</div></td>
                <td>
                  <details><summary>{s.tools.length} tools</summary>
                    {s.tools.map((t) => <div key={t.name} title={t.description}><code>{t.gateway_name}</code></div>)}
                  </details>
                </td>
                {isAdmin && (
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button className="btn" onClick={() => setForm({ ...s, secret: "" })}>Edit</button>{" "}
                    <button className="btn" onClick={() => act(() => api(`/servers/${s.id}`, { method: "PATCH", body: { enabled: !s.enabled } }))}>{s.enabled ? "Disable" : "Enable"}</button>{" "}
                    <button className="btn danger" onClick={() => confirm(`Remove ${s.name}?`) && act(() => api(`/servers/${s.id}`, { method: "DELETE" }))}>Remove</button>
                  </td>
                )}
              </tr>
            ))}
            {list && !list.length && <tr><td colSpan={4} className="muted">No servers yet. Add one to give the team its tools.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Keys({ me }) {
  const [keys, load] = usePoll("/keys", 10000);
  const [name, setName] = useState("");
  const [fresh, setFresh] = useState(null);
  const create = async () => { const r = await api("/keys", { method: "POST", body: { name } }); setFresh(r.key); setName(""); load(); };
  const url = `${location.origin}/mcp`;
  return (
    <>
      <h2>Your API keys</h2>
      <div className="card">
        <div className="row"><input placeholder="Key name (e.g. Claude Code)" value={name} onChange={(e) => setName(e.target.value)} /><button className="btn primary" onClick={create}>Generate key</button></div>
        {fresh && (
          <>
            <p><b>Copy this key now.</b> It is shown only once.</p>
            <pre>{fresh}</pre>
            <p className="muted">Claude Code:</p>
            <pre>{`claude mcp add --transport http team-gateway ${url} --header "Authorization: Bearer ${fresh}"`}</pre>
            <p className="muted">Cursor / other clients (mcp.json):</p>
            <pre>{JSON.stringify({ mcpServers: { "team-gateway": { url, headers: { Authorization: `Bearer ${fresh}` } } } }, null, 2)}</pre>
          </>
        )}
      </div>
      <KeyTable keys={keys} reload={load} showUser={false} />
    </>
  );
}

function KeyTable({ keys, reload, showUser }) {
  return (
    <div className="card"><table>
      <thead><tr><th>Name</th>{showUser && <th>User</th>}<th>Key</th><th>Created</th><th>Last used</th><th></th></tr></thead>
      <tbody>{(keys || []).map((k) => (
        <tr key={k.id}><td>{k.name}</td>{showUser && <td>{k.user_email}</td>}<td><code>{k.prefix}…</code></td><td>{fmt(k.created_at)}</td><td>{fmt(k.last_used_at)}</td>
          <td>{k.revoked_at ? <span className="badge disabled">Revoked</span> : <button className="btn danger" onClick={async () => { await api(`/keys/${k.id}`, { method: "DELETE" }); reload(); }}>Revoke</button>}</td></tr>
      ))}</tbody>
    </table></div>
  );
}

function Members() {
  const [users, loadU] = usePoll("/users");
  const [keys, loadK] = usePoll("/keys?all=1", 10000);
  const [inv, setInv] = useState({ email: "", role: "member" });
  const [link, setLink] = useState("");
  const [err, setErr] = useState("");
  const invite = async () => { setErr(""); try { const r = await api("/invites", { method: "POST", body: inv }); setLink(`${location.origin}/accept?token=${r.token}`); setInv({ ...inv, email: "" }); } catch (e) { setErr(e.message); } };
  const patch = async (id, body) => { setErr(""); try { await api(`/users/${id}`, { method: "PATCH", body }); loadU(); } catch (e) { setErr(e.message); } };
  return (
    <>
      <h2>Team members</h2>
      <div className="card">
        <div className="row"><input placeholder="Email" value={inv.email} onChange={(e) => setInv({ ...inv, email: e.target.value })} />
          <select value={inv.role} onChange={(e) => setInv({ ...inv, role: e.target.value })}><option value="member">Member</option><option value="admin">Admin</option></select>
          <button className="btn primary" onClick={invite}>Create invite link</button></div>
        {err && <p className="err">{err}</p>}
        {link && <><p className="muted">Send this link to the new member. It works once and expires in 7 days.</p><pre>{link}</pre></>}
      </div>
      <div className="card"><table>
        <thead><tr><th>Member</th><th>Role</th><th>Status</th><th></th></tr></thead>
        <tbody>{(users || []).map((u) => (
          <tr key={u.id}><td>{u.name}<div className="muted">{u.email}</div></td><td>{u.role}</td><td>{u.active ? "Active" : "Deactivated"}</td>
            <td><button className="btn" onClick={() => patch(u.id, { active: !u.active })}>{u.active ? "Deactivate" : "Reactivate"}</button></td></tr>
        ))}</tbody>
      </table></div>
      <h3>All API keys</h3>
      <KeyTable keys={keys} reload={loadK} showUser />
    </>
  );
}

function Audit() {
  const [rows, , error] = usePoll("/audit?limit=300", 4000);
  return (
    <>
      <h2>Audit log</h2>{error && <p className="err">{error}</p>}
      <div className="card" style={{ overflowX: "auto" }}><table>
        <thead><tr><th>Time</th><th>User</th><th>Via</th><th>Server</th><th>Tool</th><th>Duration</th><th>Outcome</th></tr></thead>
        <tbody>{(rows || []).map((r) => (
          <tr key={r.id}><td>{fmt(r.ts)}</td><td>{r.user_email}</td><td>{r.source}</td><td>{r.server_slug}</td><td><code>{r.tool}</code></td><td>{r.duration_ms} ms</td>
            <td><span className={`badge ${r.status}`}>{r.status}</span>{r.error && <div className="muted">{r.error}</div>}</td></tr>
        ))}</tbody>
      </table></div>
    </>
  );
}

function Chat() {
  const [msgs, setMsgs] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const send = async () => {
    if (!text.trim() || busy) return;
    const next = [...msgs, { role: "user", content: text }];
    setMsgs(next); setText(""); setBusy(true);
    try {
      const r = await api("/chat", { method: "POST", body: { messages: next.map(({ role, content }) => ({ role, content })) } });
      setMsgs([...next, { role: "assistant", content: r.reply, toolCalls: r.toolCalls }]);
    } catch (e) { setMsgs([...next, { role: "assistant", content: `Error: ${e.message}` }]); }
    setBusy(false);
  };
  return (
    <>
      <h2>Chat agent</h2>
      <div className="card">
        <div className="chat">
          {!msgs.length && <p className="muted">Ask about your store, e.g. “Create a product called Mug at 12.50” or “What orders came in today?”. Tool calls are shown under each answer.</p>}
          {msgs.map((m, i) => (
            <div key={i} className={`msg ${m.role}`}>{m.content}
              {(m.toolCalls || []).map((t, j) => (
                <details key={j} className="tool"><summary>{t.isError ? "✗" : "✓"} <code>{t.name}</code></summary>
                  <pre>{JSON.stringify(t.args, null, 2)}</pre><pre>{t.result}</pre></details>
              ))}
            </div>
          ))}
          {busy && <p className="muted">Working…</p>}
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          <input style={{ flex: 1 }} placeholder="Ask something" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} />
          <button className="btn primary" disabled={busy} onClick={send}>Send</button>
        </div>
      </div>
    </>
  );
}

export default function App() {
  const params = new URLSearchParams(location.search);
  const [me, setMe] = useState(undefined);
  const [tab, setTab] = useState("servers");
  useEffect(() => { api("/me").then(setMe).catch(() => setMe(null)); }, []);
  if (location.pathname === "/accept") return <Accept token={params.get("token")} />;
  if (me === undefined) return null;
  if (me === null) return <Login />;
  const tabs = [["servers", "Servers"], ["chat", "Chat"], ["keys", "API keys"], ...(me.role === "admin" ? [["members", "Members"]] : []), ["audit", "Audit log"]];
  return (
    <>
      <header>
        <b>Team MCP Gateway</b>
        <nav>{tabs.map(([k, l]) => <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>)}</nav>
        <span className="muted" style={{ color: "#c9d1cc" }}>{me.email} ({me.role})</span>
        <button className="btn" onClick={async () => { await api("/auth/logout", { method: "POST" }); location.reload(); }}>Sign out</button>
      </header>
      <main>
        {tab === "servers" && <Servers me={me} />}{tab === "chat" && <Chat />}{tab === "keys" && <Keys me={me} />}
        {tab === "members" && <Members />}{tab === "audit" && <Audit />}
      </main>
    </>
  );
}
