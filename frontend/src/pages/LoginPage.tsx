import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { ErrorText } from "../components/ui";
import { useAuth } from "../lib/auth";
import { useAction } from "../lib/useApi";

export function LoginPage() {
  const { user, login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const submit = useAction(login);

  if (user) return <Navigate to="/" replace />;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void submit.run(email, password);
  };

  return (
    <form className="card login" onSubmit={onSubmit}>
      <h1>DocIntake</h1>
      <label>
        Email
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
      </label>
      <label>
        Password
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </label>
      <button className="primary" disabled={submit.busy}>
        {submit.busy ? "Signing in…" : "Sign in"}
      </button>
      <ErrorText error={submit.error} />
    </form>
  );
}
