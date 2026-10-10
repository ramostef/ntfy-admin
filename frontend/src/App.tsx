
import {
  Activity,
  Bell,
  BookOpen,
  CheckCircle2,
  LayoutDashboard,
  LockKeyhole,
  LogOut,
  Menu,
  Radio,
  Settings,
  ShieldCheck,
  Smartphone,
  Users,
} from "lucide-react";
import { useEffect, useState } from "react";
import "./App.css";

type DemoAccount = {
  id: number;
  username: string;
  role: string;
  status: string;
  created_at: string;
};

const sections = [
  { name: "Vue d’ensemble", icon: LayoutDashboard },
  { name: "Comptes", icon: Users },
  { name: "Téléphones", icon: Smartphone },
  { name: "Autorisations", icon: ShieldCheck },
  { name: "Notifications", icon: Bell },
  { name: "Historique", icon: BookOpen },
  { name: "Sécurité", icon: LockKeyhole },
  { name: "Paramètres", icon: Settings },
];

export default function App() {
  const [active, setActive] = useState("Vue d’ensemble");
  const [authenticated, setAuthenticated] = useState(false);
  const [authChecking, setAuthChecking] = useState(true);
  const [loginPassword, setLoginPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [loggingIn, setLoggingIn] = useState(false);
  const [accountSearch, setAccountSearch] = useState("");
  const [apiStatus, setApiStatus] = useState<
    "checking" | "online" | "offline"
  >("checking");

const [showAccountForm, setShowAccountForm] = useState(false);
  const [newUsername, setNewUsername] = useState("");
  const [newRole, setNewRole] = useState("Téléphone");
  const [accounts, setAccounts] = useState<DemoAccount[]>([]);
  const [accountsLoading, setAccountsLoading] = useState(true);
  const [accountsError, setAccountsError] = useState("");
  const [savingAccount, setSavingAccount] = useState(false);
  const [accountMessage, setAccountMessage] = useState("");
  const allAccounts = accounts;
  
  useEffect(() => {
    let mounted = true;

    async function checkSession() {
      try {
        const response = await fetch("/api/me", {
          cache: "no-store",
        });

        if (mounted) {
          setAuthenticated(response.ok);
        }
      } catch {
        if (mounted) {
          setAuthenticated(false);
        }
      } finally {
        if (mounted) {
          setAuthChecking(false);
        }
      }
    }

    void checkSession();

    return () => {
      mounted = false;
    };
  }, []);

  async function handleLogin(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoggingIn(true);
    setLoginError("");

    try {
      const response = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: loginPassword }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Connexion refusée.");
      }

      setAuthenticated(true);
      setLoginPassword("");
      setLoginError("");
    } catch (error) {
      setLoginError(
        error instanceof Error
          ? error.message
          : "Impossible de joindre le serveur."
      );
    } finally {
      setLoggingIn(false);
    }
  }

  async function handleLogout() {
    try {
      await fetch("/api/logout", { method: "POST" });
    } finally {
      setAuthenticated(false);
      setLoginPassword("");
      setActive("Vue d’ensemble");
    }
  }

  useEffect(() => {
    let mounted = true;

    async function checkApi() {
      try {
        const response = await fetch("/api/health", {
          cache: "no-store",
        });

        if (!response.ok) {
          throw new Error("API indisponible");
        }

        const data: { status: string } = await response.json();

        if (mounted) {
          setApiStatus(data.status === "ok" ? "online" : "offline");
        }
      } catch {
        if (mounted) {
          setApiStatus("offline");
        }
      }
    }

    void checkApi();

    const interval = window.setInterval(() => {
      void checkApi();
    }, 10000);

    return () => {
      mounted = false;
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    let mounted = true;

    async function loadAccounts() {
      try {
        const response = await fetch("/api/accounts", {
          cache: "no-store",
        });
        if (!response.ok) {
          throw new Error("Impossible de charger les comptes.");
        }
        const data: DemoAccount[] = await response.json();
        if (mounted) {
          setAccounts(data);
          setAccountsError("");
        }
      } catch {
        if (mounted) {
          setAccountsError("Chargement impossible. Vérifie que l’API est en ligne.");
        }
      } finally {
        if (mounted) setAccountsLoading(false);
      }
    }

    void loadAccounts();
    return () => {
      mounted = false;
    };
  }, [authenticated]);

	
  if (authChecking) {
    return (
      <div className="login-screen">
        <div className="login-card">
          <h1>ntfy-admin</h1>
          <p>Vérification de la session administrateur…</p>
        </div>
      </div>
    );
  }

  if (!authenticated) {
    return (
      <div className="login-screen">
        <form className="login-card" onSubmit={handleLogin}>
          <div className="login-brand-icon">
            <LockKeyhole size={26} />
          </div>
          <h1>ntfy-admin</h1>
          <p>Connecte-toi pour accéder au centre de contrôle.</p>

          <label htmlFor="admin-password">Mot de passe administrateur</label>
          <input
            id="admin-password"
            type="password"
            autoComplete="current-password"
            value={loginPassword}
            onChange={(event) => setLoginPassword(event.target.value)}
            required
            autoFocus
          />

          {loginError && <p className="login-error" role="alert">{loginError}</p>}

          <button type="submit" disabled={loggingIn}>
            {loggingIn ? "Connexion…" : "Se connecter"}
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="app-shell">

      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon"><Radio size={23} /></div>
          <div>
            <strong>ntfy-admin</strong>
            <span>Centre de contrôle</span>
          </div>
        </div>

        <div className="nav-label">ADMINISTRATION</div>
        <nav>
          {sections.map(({ name, icon: Icon }) => (
            <button
              key={name}
              className={`nav-item ${active === name ? "active" : ""}`}
              onClick={() => setActive(name)}
            >
              <Icon size={18} />
              <span>{name}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="secure-label"><LockKeyhole size={15} /> Accès sécurisé à prévoir</div>
          <div className="version">ntfy-admin · Version 0.1.0</div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb"><span>Administration</span> / {active}</div>
         
          <div className="profile">
            <div className="avatar">A</div>
            <div>
              <strong>Administrateur</strong>
              <span>Session sécurisée</span>
            </div>
            <button
              type="button"
              className="logout-button"
              onClick={handleLogout}
            >
              <LogOut size={16} />
              Déconnexion
            </button>
          </div>
        </header>

        <div className="page-content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">CENTRE DE CONTRÔLE</div>
              <h1>{active}</h1>
              <p>Gérez votre infrastructure de notifications depuis un seul endroit.</p>
            </div>
            <div className="status-pill">
            <span className="status-dot" />
            {apiStatus === "checking"
              ? "Vérification API…"
              : apiStatus === "online"
                ? "API en ligne"
                : "API hors ligne"}
          </div>
          </div>

          {active === "Vue d’ensemble" ? (
            <>
              <div className="metrics-grid">
                <Metric icon={<Radio />} label="Serveur ntfy" value="À connecter" note="Connexion non configurée" />
                <Metric icon={<Users />} label="Comptes" value={String(accounts.length)} note="Valeur indicative, non vérifiée" />
                <Metric icon={<Smartphone />} label="Téléphones" value="À vérifier" note="Inventaire non connecté" />
                <Metric icon={<Activity />} label="API admin" value="En ligne" note="Interface de test locale" />
              </div>

              <section className="panel">
                <div className="panel-heading">
                  <div><h2>État des services</h2><p>Vue locale du prototype</p></div>
                  <span className="tag">DÉVELOPPEMENT</span>
                </div>
                <div className="service-row">
                  <div className="service-icon"><Activity size={19} /></div>
                  <div className="service-info"><strong>API ntfy-admin</strong><span>Backend FastAPI · port 8000</span></div>
                  <span className="service-state"><span className="status-dot" /> Testé précédemment</span>
                </div>
                <div className="service-row">
                  <div className="service-icon"><Radio size={19} /></div>
                  <div className="service-info"><strong>Serveur ntfy</strong><span>ntfy-pc-home.duckdns.org</span></div>
                  <span className="service-state pending">Non connecté</span>
                </div>
                <div className="service-row">
                  <div className="service-icon"><ShieldCheck size={19} /></div>
                  <div className="service-info"><strong>Authentification admin</strong><span>À développer avant tout accès distant</span></div>
                  <span className="service-state pending">À configurer</span>
                </div>
              </section>

              <div className="notice">
                <CheckCircle2 size={19} />
                <div><strong>Base du projet créée</strong><p>Le frontend et le backend sont en place. Les données affichées ici ne constituent pas encore un inventaire réel du serveur.</p></div>
              </div>
            </>
         
          ) : active === "Comptes" ? (
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <h2>Gestion des comptes</h2>
                  <p>Vue de démonstration — données non connectées au serveur</p>
                </div>
                <span className="tag">PROTOTYPE</span>
              </div>

              <button
                className="add-account-button"
                onClick={() => {
                  setShowAccountForm(!showAccountForm);
                  setAccountMessage("");
                }}
              >
                {showAccountForm ? "Annuler" : "+ Ajouter un compte"}
              </button>

              {showAccountForm && (
                <form
                  className="account-form"
                  onSubmit={async (event) => {
                    event.preventDefault();
                    const username = newUsername.trim();

                    if (!/^[a-zA-Z0-9_-]+$/.test(username)) {
                      setAccountMessage(
                        "Utilise uniquement des lettres, chiffres, tirets ou underscores."
                      );
                      return;
                    }

                    setSavingAccount(true);
                    setAccountMessage("");

                    try {
                      const response = await fetch("/api/accounts", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                          username,
                          role: newRole,
                        }),
                      });

                      const result = await response.json();

                      if (!response.ok) {
                        throw new Error(
                          result.detail || "Impossible d’ajouter le compte."
                        );
                      }

                      setAccounts((current) => [...current, result]);
                      setNewUsername("");
                      setNewRole("Téléphone");
                      setAccountMessage("Compte enregistré dans SQLite.");
                      setShowAccountForm(false);
                    } catch (error) {
                      setAccountMessage(
                        error instanceof Error
                          ? error.message
                          : "Une erreur est survenue."
                      );
                    } finally {
                      setSavingAccount(false);
                    }
                  }}
                >
                  <label htmlFor="new-username">Nom d’utilisateur</label>
                  <input
                    id="new-username"
                    value={newUsername}
                    onChange={(event) => setNewUsername(event.target.value)}
                    placeholder="Ex. tel022"
                    required
                  />

                  <label htmlFor="new-role">Rôle</label>
                  <select
                    id="new-role"
                    value={newRole}
                    onChange={(event) => setNewRole(event.target.value)}
                  >
                    <option>Téléphone</option>
                    <option>Administrateur</option>
                    <option>Observateur</option>
                  </select>

                  <button
                    type="submit"
                    className="add-account-button"
                    disabled={savingAccount}
                  >
                    {savingAccount ? "Enregistrement…" : "Ajouter"}
                  </button>
                </form>
              )}

              {accountMessage && <p role="status">{accountMessage}</p>}
              {accountsError && <p role="alert">{accountsError}</p>}
              {accountsLoading && <p>Chargement des comptes…</p>}

              <input
                className="account-search"
                type="search"
                placeholder="Rechercher un compte..."
                value={accountSearch}
                onChange={(event) => setAccountSearch(event.target.value)}
              />

              {allAccounts
                .filter((account) =>
                  `${account.username} ${account.role} ${account.status}`
                    .toLowerCase()
                    .includes(accountSearch.toLowerCase())
                )
                .map((account) => (
                  <div className="service-row" key={account.username}>
                    <div className="service-icon">
                      <Users size={19} />
                    </div>
                    <div className="service-info">
                      <strong>{account.username}</strong>
                      <span>{account.role}</span>
                    </div>
                    <span className="service-state pending">
                      {account.status}
                    </span>
                  </div>
                ))}
            </section>
          ) : (
            <section className="panel placeholder">

              <div className="placeholder-icon"><Menu size={24} /></div>
              <h2>{active}</h2>
              <p>Cette rubrique est prête à être développée.</p>
              <span>Fonctionnalité non connectée pour le moment</span>
            </section>
          )}
        </div>
      </main>
    </div>
  );
}

function Metric({
  icon,
  label,
  value,
  note,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  note: string;
}) {
  return (
    <section className="metric-card">
      <div className="metric-top"><span>{label}</span><div className="metric-icon">{icon}</div></div>
      <div className="metric-value">{value}</div>
      <div className="metric-note">{note}</div>
    </section>
  );
}
