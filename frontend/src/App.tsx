
import {
  Activity,
  Bell,
  BookOpen,
  BriefcaseBusiness,
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

type NtfyAccount = {
  username: string;
  role: string;
  tier: string;
  permissions: string[];
};

type Phone = {
  id: number;
  phone_id: string;
  name: string;
  ntfy_username: string | null;
  status: "active" | "disabled";
  notes: string | null;
  created_at: string;
  updated_at: string;
};

type InterimWorker = {
  id: number;
  full_name: string;
  ntfy_username: string;
  start_date: string;
  end_date: string;
  status: "active" | "closed";
  decision: "pending" | "extended" | "access_reviewed" | "keep_access";
  decision_note: string | null;
  alert: "overdue" | "due_today" | "upcoming" | "closed";
  phones: { phone_id: string; name: string; status: string }[];
};


type AuditEvent = {
  id: number;
  actor_username: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  details_json: string | null;
  created_at: string;
};

const sections = [
  { name: "Vue d’ensemble", icon: LayoutDashboard },
  { name: "Comptes", icon: Users },
  { name: "Téléphones", icon: Smartphone },
  { name: "Intérimaires", icon: BriefcaseBusiness },
  { name: "Autorisations", icon: ShieldCheck },
  { name: "Notifications", icon: Bell },
  { name: "Historique", icon: BookOpen },
  { name: "Sécurité", icon: LockKeyhole },
  { name: "Paramètres", icon: Settings },
];


async function fetchNtfyHealth(): Promise<"online" | "offline"> {
  try {
    const response = await fetch("/api/ntfy/health", {
      cache: "no-store",
    });

    if (!response.ok) return "offline";

    const data: { status: string } = await response.json();
    return data.status === "online" ? "online" : "offline";
  } catch {
    return "offline";
  }
}


export default function App() {
  const [active, setActive] = useState("Vue d’ensemble");

  const [notificationRecipients, setNotificationRecipients] = useState<string[]>([]);
  const [notificationTitle, setNotificationTitle] = useState("");
  const [notificationBody, setNotificationBody] = useState("");
  const [notificationPreview, setNotificationPreview] = useState(false);
  const [notificationSending, setNotificationSending] = useState(false);
  const [notificationResult, setNotificationResult] = useState("");

  async function handleSendNotification() {
    if (notificationSending) return;

    const selectedPhones = phones.filter((phone) =>
      notificationRecipients.includes(phone.phone_id) && phone.status === "active"
    );
    if (selectedPhones.length === 0 || !notificationTitle.trim() || !notificationBody.trim()) {
      setNotificationResult("Vérifiez le titre, le message et les destinataires actifs.");
      return;
    }

    const names = selectedPhones.map((phone) => `${phone.name} (${phone.phone_id})`).join("\\n");
    const confirmed = window.confirm(
      `Confirmer l'envoi de cette notification ?\\n\\nDestinataires :\\n${names}\\n\\nTitre : ${notificationTitle.trim()}\\n\\nMessage :\\n${notificationBody.trim()}`
    );
    if (!confirmed) return;

    setNotificationSending(true);
    setNotificationResult("");

    try {
      const response = await fetch("/api/notifications/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          recipients: selectedPhones.map((phone) => phone.phone_id),
          title: notificationTitle.trim(),
          body: notificationBody.trim(),
        }),
      });

      const result: {
        message?: string;
        accepted_count?: number;
        failed_count?: number;
        detail?: string | { message?: string };
      } = await response.json();

      if (!response.ok) {
        const detail = typeof result.detail === "string"
          ? result.detail
          : result.detail?.message;
        throw new Error(detail || "L'envoi a échoué.");
      }

      setNotificationResult(
        `${result.message || "Envoi traité."} Destinataires acceptés : ${result.accepted_count ?? 0}. Échecs : ${result.failed_count ?? 0}.`
      );
      setNotificationPreview(false);
    } catch (error) {
      setNotificationResult(
        error instanceof Error ? error.message : "Erreur lors de l'envoi."
      );
    } finally {
      setNotificationSending(false);
    }
  }

  const [authenticated, setAuthenticated] = useState(false);
  const [authChecking, setAuthChecking] = useState(true);
  const [loginPassword, setLoginPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [loggingIn, setLoggingIn] = useState(false);
  const [accountSearch, setAccountSearch] = useState("");
  const [apiStatus, setApiStatus] = useState<
    "checking" | "online" | "offline"
  >("checking");
  const [ntfyStatus, setNtfyStatus] = useState<
  "checking" | "online" | "offline"
  >("checking");
const [ntfyCheckingManually, setNtfyCheckingManually] = useState(false);

async function handleCheckNtfy() {
  setNtfyCheckingManually(true);

  const startedAt = Date.now();

  try {
    const status = await fetchNtfyHealth();
    const elapsed = Date.now() - startedAt;

    if (elapsed < 800) {
      await new Promise(resolve => setTimeout(resolve, 800 - elapsed));
    }

    setNtfyStatus(status);
  } finally {
    setNtfyCheckingManually(false);
  }
}

const [accounts, setAccounts] = useState<NtfyAccount[]>([]);
const [phones, setPhones] = useState<Phone[]>([]);
const [interimWorkers, setInterimWorkers] = useState<InterimWorker[]>([]);
const [interimLoading, setInterimLoading] = useState(true);
const [interimError, setInterimError] = useState("");
const [interimMessage, setInterimMessage] = useState("");
const [interimActionLoading, setInterimActionLoading] = useState(false);
const [interimDecisionNotes, setInterimDecisionNotes] = useState<Record<number, string>>({});
const [interimDecisionChoices, setInterimDecisionChoices] = useState<Record<number, InterimWorker["decision"]>>({});
const [showInterimForm, setShowInterimForm] = useState(false);
const [editingInterimWorkerId, setEditingInterimWorkerId] = useState<number | null>(null);
const [interimFullName, setInterimFullName] = useState("");
const [interimUsername, setInterimUsername] = useState("");
const [interimStartDate, setInterimStartDate] = useState("");
const [interimEndDate, setInterimEndDate] = useState("");
const [interimPhoneIds, setInterimPhoneIds] = useState<string[]>([]);

const [phoneSearch, setPhoneSearch] = useState("");
const [phoneStatusFilter, setPhoneStatusFilter] = useState<"all" | "active" | "disabled">("all");

const filteredPhones = phones.filter((phone) => {
  const query = phoneSearch.trim().toLowerCase();

  const matchesSearch =
    !query ||
    phone.phone_id.toLowerCase().includes(query) ||
    phone.name.toLowerCase().includes(query) ||
    (phone.ntfy_username ?? "").toLowerCase().includes(query) ||
    (phone.notes ?? "").toLowerCase().includes(query);

  const matchesStatus =
    phoneStatusFilter === "all" ||
    phone.status === phoneStatusFilter;

  return matchesSearch && matchesStatus;
});

const activePhonesCount = phones.filter(
  (phone) => phone.status === "active"
).length;

const disabledPhonesCount = phones.filter(
  (phone) => phone.status === "disabled"
).length;

const [phonesLoading, setPhonesLoading] = useState(true);
const [phonesError, setPhonesError] = useState("");
const [showPhoneForm, setShowPhoneForm] = useState(false);
const [phoneActionMessage, setPhoneActionMessage] = useState("");
const [phoneActionError, setPhoneActionError] = useState("");
const [phoneActionLoading, setPhoneActionLoading] = useState(false);
const [editingPhoneId, setEditingPhoneId] = useState("");
const [phoneIdInput, setPhoneIdInput] = useState("");
const [phoneNameInput, setPhoneNameInput] = useState("");
const [phoneUsernameInput, setPhoneUsernameInput] = useState("");
const [phoneStatusInput, setPhoneStatusInput] = useState<"active" | "disabled">("active");
const [phoneNotesInput, setPhoneNotesInput] = useState("");
const [accountsLoading, setAccountsLoading] = useState(true);
const [accountsError, setAccountsError] = useState("");
const [showAddAccount, setShowAddAccount] = useState(false);
const [newUsername, setNewUsername] = useState("");
const [newPassword, setNewPassword] = useState("");
const [newRole, setNewRole] = useState("user");
const [accountActionMessage, setAccountActionMessage] = useState("");
const [accountActionError, setAccountActionError] = useState("");
const [accountActionLoading, setAccountActionLoading] = useState(false);
const [permissionUser, setPermissionUser] = useState("");
const [permissionTopic, setPermissionTopic] = useState("tous-les-telephones");
const [permissionValue, setPermissionValue] = useState("read-only");
const [passwordUser, setPasswordUser] = useState("");
const [accountNewPassword, setAccountNewPassword] = useState("");
const allAccounts = accounts;

const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
const [auditLoading, setAuditLoading] = useState(false);
const [auditError, setAuditError] = useState("");


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

  useEffect(() => {
    if (!authenticated || active !== "Historique") return;

    let mounted = true;

    async function loadAuditEvents() {
      setAuditLoading(true);
      setAuditError("");

      try {
        const response = await fetch("/api/audit-events", {
          cache: "no-store",
        });

        if (!response.ok) {
          throw new Error(
            response.status === 401
              ? "Session expirée. Reconnectez-vous."
              : "Impossible de charger l’historique."
          );
        }

        const data: AuditEvent[] = await response.json();
        if (mounted) setAuditEvents(data);
      } catch (error) {
        if (mounted) {
          setAuditError(
            error instanceof Error
              ? error.message
              : "Erreur de chargement."
          );
        }
      } finally {
        if (mounted) setAuditLoading(false);
      }
    }

    void loadAuditEvents();

    return () => {
      mounted = false;
    };
  }, [authenticated, active]);

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
  if (!authenticated) {
    setNtfyStatus("checking");
    return;
  }

  let mounted = true;


async function checkNtfy() {
  const status = await fetchNtfyHealth();
  if (mounted) setNtfyStatus(status);
}


  void checkNtfy();
  const interval = window.setInterval(() => {
    void checkNtfy();
  }, 15000);

  return () => {
    mounted = false;
    window.clearInterval(interval);
  };
}, [authenticated]);


  useEffect(() => {
    let mounted = true;

    async function loadAccounts() {
      try {
        const response = await fetch("/api/ntfy/accounts", {
          cache: "no-store",
        });
        if (!response.ok) {
          throw new Error("Impossible de charger les comptes.");
        }
        const data: NtfyAccount[] = await response.json();
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


  useEffect(() => {
    let mounted = true;

    async function loadPhones() {
      try {
        const response = await fetch("/api/phones", {
          cache: "no-store",
        });

        if (!response.ok) {
          throw new Error("Impossible de charger l’inventaire.");
        }

        const data: Phone[] = await response.json();

        if (mounted) {
          setPhones(data);
          setPhonesError("");
        }
      } catch {
        if (mounted) {
          setPhonesError(
            "Chargement impossible. Vérifie que l’API est en ligne."
          );
        }
      } finally {
        if (mounted) {
          setPhonesLoading(false);
        }
      }
    }

    if (authenticated) {
      void loadPhones();
    } else {
      setPhones([]);
      setPhonesLoading(false);
    }

    return () => {
      mounted = false;
    };
  }, [authenticated]);


  useEffect(() => {
    let mounted = true;

    async function loadInterimWorkers() {
      try {
        const response = await fetch("/api/interim-workers", {
          cache: "no-store",
        });

        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(
            data.detail || "Impossible de charger les intérimaires."
          );
        }

        const data: InterimWorker[] = await response.json();

        if (mounted) {
          setInterimWorkers(data);
          setInterimError("");
        }
      } catch (error) {
        if (mounted) {
          setInterimError(
            error instanceof Error
              ? error.message
              : "Chargement des intérimaires impossible."
          );
        }
      } finally {
        if (mounted) {
          setInterimLoading(false);
        }
      }
    }

    if (authenticated) {
      setInterimLoading(true);
      void loadInterimWorkers();
    } else {
      setInterimWorkers([]);
      setInterimLoading(false);
    }

    return () => {
      mounted = false;
    };
  }, [authenticated]);

  async function handleCreateAccount(event: React.FormEvent<HTMLFormElement>) {
  event.preventDefault();
  setAccountActionMessage("");
  setAccountActionError("");

  if (newRole === "admin") {
    const confirmed = window.confirm(
      "Créer un compte administrateur lui donnera des privilèges élevés. Continuer ?"
    );
    if (!confirmed) return;
  }

  setAccountActionLoading(true);

  try {
    const response = await fetch("/api/ntfy/accounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: newUsername.trim(),
        password: newPassword,
        role: newRole,
      }),
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Création du compte impossible.");
    }

    const accountsResponse = await fetch("/api/ntfy/accounts", {
      cache: "no-store",
    });

    if (!accountsResponse.ok) {
      throw new Error(
        "Compte créé, mais impossible d'actualiser la liste."
      );
    }

    const updatedAccounts: NtfyAccount[] = await accountsResponse.json();
    setAccounts(updatedAccounts);
    setNewUsername("");
    setNewPassword("");
    setNewRole("user");
    setShowAddAccount(false);
    setAccountActionMessage(
      `Le compte ${data.username} a été créé.`
    );
  } catch (error) {
    setAccountActionError(
      error instanceof Error
        ? error.message
        : "Erreur pendant la création."
    );
  } finally {
    setAccountActionLoading(false);
  }
}


function handleEditInterimWorker(worker: InterimWorker) {
  setEditingInterimWorkerId(worker.id);
  setInterimFullName(worker.full_name);
  setInterimUsername(worker.ntfy_username);
  setInterimStartDate(worker.start_date);
  setInterimEndDate(worker.end_date);
  setInterimPhoneIds(worker.phones.map((phone) => phone.phone_id));
  setInterimError("");
  setInterimMessage("");
  setShowInterimForm(true);
}

async function handleUpdateInterimWorker(event: React.FormEvent<HTMLFormElement>) {
  event.preventDefault();
  setInterimError("");
  setInterimMessage("");

  if (!editingInterimWorkerId) {
    setInterimError("Aucune fiche sélectionnée pour modification.");
    return;
  }
  if (!interimFullName.trim() || !interimStartDate || !interimEndDate) {
    setInterimError("Merci de remplir tous les champs obligatoires.");
    return;
  }
  if (interimEndDate < interimStartDate) {
    setInterimError("La date de fin doit être égale ou postérieure à la date de début.");
    return;
  }

  setInterimActionLoading(true);
  try {
    const response = await fetch(`/api/interim-workers/${editingInterimWorkerId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        full_name: interimFullName.trim(),
        start_date: interimStartDate,
        end_date: interimEndDate,
        phone_ids: interimPhoneIds,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || "Modification de la fiche impossible.");
    }

    const listResponse = await fetch("/api/interim-workers", { cache: "no-store" });
    if (!listResponse.ok) {
      throw new Error("Modification enregistrée, mais actualisation de la liste impossible.");
    }

    setInterimWorkers(await listResponse.json());
    setShowInterimForm(false);
    setEditingInterimWorkerId(null);
    setInterimMessage("Fiche modifiée. Le compte ntfy et ses permissions n'ont pas été modifiés.");
  } catch (error) {
    setInterimError(error instanceof Error ? error.message : "Erreur pendant la modification.");
  } finally {
    setInterimActionLoading(false);
  }
}

async function handleSaveInterimWorker(event: React.FormEvent<HTMLFormElement>) {
  event.preventDefault();
  setInterimError("");
  setInterimMessage("");

  if (!interimFullName.trim() || !interimUsername.trim() ||
      !interimStartDate || !interimEndDate) {
    setInterimError("Merci de remplir tous les champs obligatoires.");
    return;
  }

  if (interimEndDate < interimStartDate) {
    setInterimError("La date de fin doit être égale ou postérieure à la date de début.");
    return;
  }

  setInterimActionLoading(true);
  try {
    const response = await fetch("/api/interim-workers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        full_name: interimFullName.trim(),
        ntfy_username: interimUsername.trim(),
        start_date: interimStartDate,
        end_date: interimEndDate,
        phone_ids: interimPhoneIds,
      }),
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || "Création de la fiche impossible.");
    }

    const listResponse = await fetch("/api/interim-workers", {
      cache: "no-store",
    });
    if (!listResponse.ok) {
      throw new Error("Fiche créée, mais actualisation de la liste impossible.");
    }

    const updatedWorkers: InterimWorker[] = await listResponse.json();
    setInterimWorkers(updatedWorkers);
    setShowInterimForm(false);
    setInterimFullName("");
    setInterimUsername("");
    setInterimStartDate("");
    setInterimEndDate("");
    setInterimPhoneIds([]);
    setInterimMessage("Fiche intérimaire créée.");
  } catch (error) {
    setInterimError(
      error instanceof Error ? error.message : "Erreur pendant la création."
    );
  } finally {
    setInterimActionLoading(false);
  }
}



async function handleInterimAction(
  worker: InterimWorker,
  action: "decision" | "close",
  decision?: "pending" | "extended" | "access_reviewed" | "keep_access",
) {
  setInterimError("");
  setInterimMessage("");

  if (action === "close") {
    const confirmed = window.confirm(
      `Clôturer la fiche de ${worker.full_name} ? Cette action ne supprimera pas le compte ntfy et ne modifiera aucune permission.`
    );
    if (!confirmed) return;
  }

  setInterimActionLoading(true);
  try {
    const note = (interimDecisionNotes[worker.id] ?? "").trim();
    const response = await fetch(`/api/interim-workers/${worker.id}/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(action === "close" ? { note } : { decision, note }),
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || "Action impossible.");
    }

    const listResponse = await fetch("/api/interim-workers", { cache: "no-store" });
    if (!listResponse.ok) {
      throw new Error("Action enregistrée, mais actualisation de la liste impossible.");
    }

    const updatedWorkers: InterimWorker[] = await listResponse.json();
    setInterimWorkers(updatedWorkers);
    setInterimMessage(
      action === "close"
        ? `Fiche de ${worker.full_name} clôturée. Le compte ntfy et ses permissions n'ont pas été modifiés.`
        : "Décision enregistrée."
    );
  } catch (error) {
    setInterimError(error instanceof Error ? error.message : "Erreur pendant l'action.");
  } finally {
    setInterimActionLoading(false);
  }
}

async function handleSavePhone(event: React.FormEvent<HTMLFormElement>) {
  event.preventDefault();
  setPhoneActionMessage("");
  setPhoneActionError("");

  const phoneId = editingPhoneId || phoneIdInput.trim();
  const name = phoneNameInput.trim();

  if (!name) {
    setPhoneActionError("Le nom du téléphone est obligatoire.");
    return;
  }

  setPhoneActionLoading(true);

  try {
    const response = await fetch(
      editingPhoneId
        ? `/api/phones/${encodeURIComponent(editingPhoneId)}`
        : "/api/phones",
      {
        method: editingPhoneId ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          phone_id: phoneId,
          name,
          ntfy_username: phoneUsernameInput.trim() || null,
          status: phoneStatusInput,
          notes: phoneNotesInput.trim() || null,
        }),
      }
    );

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Enregistrement impossible.");
    }

    const listResponse = await fetch("/api/phones", {
      cache: "no-store",
    });

    if (!listResponse.ok) {
      throw new Error("Fiche enregistrée, mais actualisation impossible.");
    }

    const updatedPhones: Phone[] = await listResponse.json();
    setPhones(updatedPhones);
    setShowPhoneForm(false);
    setEditingPhoneId("");
    setPhoneIdInput("");
    setPhoneNameInput("");
    setPhoneUsernameInput("");
    setPhoneStatusInput("active");
    setPhoneNotesInput("");
    setPhoneActionMessage(
      editingPhoneId
        ? "Téléphone modifié."
        : "Téléphone ajouté à l’inventaire."
    );
    setPhonesError("");
  } catch (error) {
    setPhoneActionError(
      error instanceof Error
        ? error.message
        : "Erreur pendant l’enregistrement."
    );
  } finally {
    setPhoneActionLoading(false);
  }
}


function handleEditPhone(phone: Phone) {
  setEditingPhoneId(phone.phone_id);
  setPhoneIdInput(phone.phone_id);
  setPhoneNameInput(phone.name);
  setPhoneUsernameInput(phone.ntfy_username ?? "");
  setPhoneStatusInput(phone.status);
  setPhoneNotesInput(phone.notes ?? "");
  setPhoneActionMessage("");
  setPhoneActionError("");
  setShowPhoneForm(true);
}

async function handleDeletePhone(phone: Phone) {
  const confirmed = window.confirm(
    `Retirer « ${phone.name} » (${phone.phone_id}) de l’inventaire ?\n\nLe compte ntfy associé ne sera pas supprimé.`
  );

  if (!confirmed) {
    return;
  }

  setPhoneActionMessage("");
  setPhoneActionError("");
  setPhoneActionLoading(true);

  try {
    const response = await fetch(
      `/api/phones/${encodeURIComponent(phone.phone_id)}`,
      { method: "DELETE" }
    );

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Suppression impossible.");
    }

    const listResponse = await fetch("/api/phones", {
      cache: "no-store",
    });

    if (!listResponse.ok) {
      throw new Error("Suppression effectuée, mais actualisation impossible.");
    }

    const updatedPhones: Phone[] = await listResponse.json();
    setPhones(updatedPhones);
    setPhoneActionMessage("Téléphone retiré de l’inventaire.");
  } catch (error) {
    setPhoneActionError(
      error instanceof Error
        ? error.message
        : "Erreur pendant la suppression."
    );
  } finally {
    setPhoneActionLoading(false);
  }
}

async function handlePermissionChange(
  event: React.FormEvent<HTMLFormElement>
) {
  event.preventDefault();
  setAccountActionMessage("");
  setAccountActionError("");

  if (!permissionUser) {
    setAccountActionError("Sélectionne un compte.");
    return;
  }

  setAccountActionLoading(true);

  try {
    const response = await fetch(
      `/api/ntfy/accounts/${encodeURIComponent(permissionUser)}/permissions`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic: permissionTopic,
          permission: permissionValue,
        }),
      }
    );

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Modification des permissions impossible.");
    }

    const accountsResponse = await fetch("/api/ntfy/accounts", {
      cache: "no-store",
    });

    if (!accountsResponse.ok) {
      throw new Error("Permission modifiée, mais actualisation impossible.");
    }

    const updatedAccounts: NtfyAccount[] = await accountsResponse.json();
    setAccounts(updatedAccounts);
    setAccountActionMessage(
      `Permission mise à jour pour ${permissionUser} sur ${permissionTopic}.`
    );
  } catch (error) {
    setAccountActionError(
      error instanceof Error
        ? error.message
        : "Erreur pendant la modification des permissions."
    );
  } finally {
    setAccountActionLoading(false);
  }
}

async function handleChangeAccountPassword(
  event: React.FormEvent<HTMLFormElement>
) {
  event.preventDefault();
  setAccountActionMessage("");
  setAccountActionError("");

  if (!passwordUser) {
    setAccountActionError("Sélectionne un compte.");
    return;
  }

  if (accountNewPassword.length < 12) {
    setAccountActionError("Le mot de passe doit contenir au moins 12 caractères.");
    return;
  }

  setAccountActionLoading(true);

  try {
    const response = await fetch(
      `/api/ntfy/accounts/${encodeURIComponent(passwordUser)}/password`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: accountNewPassword }),
      }
    );

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Modification du mot de passe impossible.");
    }

    setAccountNewPassword("");
    setAccountActionMessage(
      `Mot de passe modifié pour ${passwordUser}.`
    );
  } catch (error) {
    setAccountActionError(
      error instanceof Error
        ? error.message
        : "Erreur pendant la modification du mot de passe."
    );
  } finally {
    setAccountActionLoading(false);
  }
}

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

<Metric
  icon={<Radio />}
  label="Serveur ntfy"
  value={
    ntfyStatus === "checking"
      ? "Vérification…"
      : ntfyStatus === "online"
        ? "En ligne"
        : "Hors ligne"
  }
  note="Disponibilité du serveur"
/>
<Metric
  icon={<Users />}
  label="Comptes"
  value={String(accounts.length)}
  note="Comptes récupérés depuis ntfy"
/>

               <Metric
  icon={<Smartphone />}
  label="Téléphones"
  value={String(phones.length)}
  note={`${activePhonesCount} actifs · ${disabledPhonesCount} désactivés`}
/>

<Metric
  icon={<Activity />}
  label="API admin"
  value={
    apiStatus === "checking"
      ? "Vérification…"
      : apiStatus === "online"
        ? "En ligne"
        : "Hors ligne"
  }
  note="État actualisé automatiquement"
/>

              </div>

              <section className="panel">
                <div className="panel-heading">
  <div>
    <h2>État des services</h2>
    <p>Disponibilité actualisée automatiquement</p>
  </div>
  <button
    type="button"
    className="health-refresh-button"
    onClick={handleCheckNtfy}
    disabled={ntfyCheckingManually}
  >
    <Activity size={15} />
    {ntfyCheckingManually ? "Vérification…" : "Vérifier maintenant"}
  </button>

                  <span className="tag">DÉVELOPPEMENT</span>
                </div>
                <div className="service-row">
                  <div className="service-icon"><Activity size={19} /></div>
                  <div className="service-info"><strong>API ntfy-admin</strong><span>Backend FastAPI · port 8000</span></div>

<span
  className={`service-state ${
    apiStatus === "online"
      ? "online"
      : apiStatus === "checking"
        ? "pending"
        : "offline"
  }`}
>
  <span
    className={`status-dot ${
      apiStatus === "checking"
        ? "status-checking"
        : apiStatus === "offline"
          ? "status-offline"
          : ""
    }`}
  />
  {apiStatus === "checking"
    ? "Vérification…"
    : apiStatus === "online"
      ? "En ligne"
      : "Hors ligne"}
</span>

                </div>
                <div className="service-row">
                  <div className="service-icon"><Radio size={19} /></div>
                  <div className="service-info"><strong>Serveur ntfy</strong><span>ntfy-pc-home.duckdns.org</span></div>

<span
  className={`service-state ${
    ntfyStatus === "online"
      ? "online"
      : ntfyStatus === "checking"
        ? "pending"
        : "offline"
  }`}
>
  {ntfyStatus === "checking"
    ? "Vérification…"
    : ntfyStatus === "online"
      ? "En ligne"
      : "Hors ligne"}
</span>

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
                  <p>Comptes réels récupérés depuis le serveur ntfy</p>
                </div>
                <span className="tag">NTFY</span>
              </div>
		<div className="account-actions">
  <button
    type="button"
    className="add-account-button"
    onClick={() => {
      setShowAddAccount(!showAddAccount);
      setAccountActionMessage("");
      setAccountActionError("");
    }}
  >
    {showAddAccount ? "Annuler" : "+ Ajouter un compte"}
  </button>
</div>

{showAddAccount && (
  <form className="account-form" onSubmit={handleCreateAccount}>
    <h3>Créer un compte ntfy</h3>

    <label htmlFor="new-username">Identifiant</label>
    <input
      id="new-username"
      value={newUsername}
      onChange={(event) => setNewUsername(event.target.value)}
      pattern="[a-zA-Z0-9_-]{1,32}"
      maxLength={32}
      autoComplete="off"
      required
    />

    <label htmlFor="new-password">Mot de passe (12 caractères minimum)</label>
    <input
      id="new-password"
      type="password"
      value={newPassword}
      onChange={(event) => setNewPassword(event.target.value)}
      minLength={12}
      maxLength={1024}
      autoComplete="new-password"
      required
    />

    <label htmlFor="new-role">Rôle</label>
    <select
      id="new-role"
      value={newRole}
      onChange={(event) => setNewRole(event.target.value)}
    >
      <option value="user">Utilisateur</option>
      <option value="admin">Administrateur</option>
    </select>

    <button
      type="submit"
      className="add-account-button"
      disabled={accountActionLoading}
    >
      {accountActionLoading ? "Création…" : "Créer le compte"}
    </button>
  </form>
)}

{accountActionMessage && (
  <div className="account-feedback account-feedback-success" role="status">
    <strong>✓ Opération réussie</strong>
    <p>{accountActionMessage}</p>
  </div>
)}

{accountActionError && (
  <div className="account-feedback account-feedback-error" role="alert">
    <strong>⚠ Une erreur est survenue</strong>
    <p>{accountActionError}</p>
  </div>
)}

<form className="account-form" onSubmit={handleChangeAccountPassword}>
  <h3>Modifier le mot de passe d’un compte</h3>

  <label htmlFor="password-user">Compte</label>
  <select
    id="password-user"
    value={passwordUser}
    onChange={(event) => setPasswordUser(event.target.value)}
    required
  >
    <option value="">Choisir un compte</option>
    {accounts
      .filter((account) => account.username !== "*" && account.username !== "admin")
      .map((account) => (
        <option key={account.username} value={account.username}>
          {account.username}
        </option>
      ))}
  </select>

  <label htmlFor="account-new-password">Nouveau mot de passe (12 caractères minimum)</label>
  <input
    id="account-new-password"
    type="password"
    value={accountNewPassword}
    onChange={(event) => setAccountNewPassword(event.target.value)}
    minLength={12}
    maxLength={1024}
    autoComplete="new-password"
    required
  />

  <button
    type="submit"
    className="add-account-button"
    disabled={accountActionLoading}
  >
    {accountActionLoading ? "Modification…" : "Modifier le mot de passe"}
  </button>
</form>


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
    `${account.username} ${account.role} ${account.permissions.join(" ")}`
      .toLowerCase()
      .includes(accountSearch.toLowerCase())
  )
  .map((account) => (
    <div className="account-card" key={account.username}>
      <div className="account-card-header">
        <div className="service-icon">
          {account.role === "admin" ? (
            <ShieldCheck size={20} />
          ) : (
            <Smartphone size={20} />
          )}
        </div>

        <div className="service-info">
          <strong>{account.username}</strong>
          <span>
            {account.role === "admin"
              ? "Administrateur"
              : account.role === "anonymous"
                ? "Accès anonyme"
                : "Compte utilisateur"}
          </span>
        </div>

        <span
          className={`account-role ${
            account.role === "admin" ? "account-role-admin" : ""
          }`}
        >
          {account.role}
        </span>
      </div>

      <div className="account-permissions">
        <strong>Permissions</strong>

        {account.permissions.map((permission, index) => {
          const isReadWrite = permission.includes("read-write");
          const isReadOnly = permission.includes("read-only");
          const isWriteOnly = permission.includes("write-only");
          const isDenied = permission.includes("deny");

          const permissionLabel = isReadWrite
            ? "Lecture et écriture"
            : isReadOnly
              ? "Lecture seule"
              : isWriteOnly
                ? "Écriture seule"
                : isDenied
                  ? "Aucun accès"
                  : "Permission";

          const permissionClass =
            isReadWrite || isWriteOnly
              ? "permission-write"
              : isReadOnly
                ? "permission-read"
                : "permission-neutral";

          return (
            <div className="permission-row" key={`${account.username}-${index}`}>
              <span className={`permission-badge ${permissionClass}`}>
                {permissionLabel}
              </span>

              <span className="permission-description">
                {permission}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  ))}

      </section>

          ) : active === "Autorisations" ? (
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <h2>Gestion des autorisations</h2>
                  <p>Choisis un compte, un sujet et les droits à appliquer.</p>
                </div>
                <span className="tag">NTFY</span>
              </div>

              {accountActionMessage && (
                <div className="account-feedback account-feedback-success" role="status">
                  <strong>✓ Opération réussie</strong>
                  <p>{accountActionMessage}</p>
                </div>
              )}

              {accountActionError && (
                <div className="account-feedback account-feedback-error" role="alert">
                  <strong>⚠ Une erreur est survenue</strong>
                  <p>{accountActionError}</p>
                </div>
              )}
              {accountsError && <p role="alert">{accountsError}</p>}
              {accountsLoading && <p>Chargement des comptes…</p>}

              <form className="account-form" onSubmit={handlePermissionChange}>
  <h3>Modifier les permissions d’un compte</h3>

  <label htmlFor="permission-user">Compte</label>
  <select
    id="permission-user"
    value={permissionUser}
    onChange={(event) => setPermissionUser(event.target.value)}
    required
  >
    <option value="">Choisir un compte</option>
    {accounts
      .filter((account) => account.username !== "*" && account.username !== "admin")
      .map((account) => (
        <option key={account.username} value={account.username}>
          {account.username}
        </option>
      ))}
  </select>

  <label htmlFor="permission-topic">Sujet</label>
  <select
    id="permission-topic"
    value={permissionTopic}
    onChange={(event) => setPermissionTopic(event.target.value)}
  >
    <option value="tous-les-telephones">tous-les-telephones</option>
    {Array.from({ length: 50 }, (_, index) => {
      const topic = `tel-${String(index + 1).padStart(3, "0")}`;
      return (
        <option key={topic} value={topic}>
          {topic}
        </option>
      );
    })}
  </select>

  <label htmlFor="permission-value">Autorisation</label>
  <select
    id="permission-value"
    value={permissionValue}
    onChange={(event) => setPermissionValue(event.target.value)}
  >
    <option value="read-only">Lecture seule</option>
    <option value="read-write">Lecture et écriture</option>
    <option value="write-only">Écriture seule</option>
    <option value="deny">Aucun accès</option>
  </select>

  <button
    type="submit"
    className="add-account-button"
    disabled={accountActionLoading}
  >
    {accountActionLoading ? "Enregistrement…" : "Enregistrer les permissions"}
  </button>
</form>
            </section>
          ) : active === "Téléphones" ? (
            <section className="panel phone-inventory-panel">
              <div className="section-heading">
                <div>
                  <h2>Inventaire des téléphones</h2>

                  <p>Gérer les appareils enregistrés, indépendamment des comptes ntfy.</p>
                </div>

                <div className="phone-stats">
                  <div className="phone-stat">
                    <span>Total enregistré</span>
                    <strong>{phones.length}</strong>
                  </div>
                  <div className="phone-stat">
                    <span>Téléphones actifs</span>
                    <strong>{activePhonesCount}</strong>
                  </div>
                  <div className="phone-stat">
                    <span>Téléphones désactivés</span>
                    <strong>{disabledPhonesCount}</strong>
                  </div>
                </div>

                <button

                  type="button"
                  onClick={() => {
                    setEditingPhoneId("");
                    setPhoneIdInput("");
                    setPhoneNameInput("");
                    setPhoneUsernameInput("");
                    setPhoneStatusInput("active");
                    setPhoneNotesInput("");
                    setPhoneActionMessage("");
                    setPhoneActionError("");
                    setShowPhoneForm(true);
                  }}
                >
                  Ajouter un téléphone
                </button>
              </div>

              {phoneActionMessage && (
                <p role="status">{phoneActionMessage}</p>
              )}
              {phoneActionError && (
                <p role="alert">{phoneActionError}</p>
              )}
              {phonesError && <p role="alert">{phonesError}</p>}

              {showPhoneForm && (
                <form onSubmit={handleSavePhone} className="phone-form">
                  <h3>
                    {editingPhoneId ? "Modifier le téléphone" : "Nouveau téléphone"}
                  </h3>

                  <label>
                    Identifiant du téléphone
                    <input
                      type="text"
                      value={phoneIdInput}
                      onChange={(event) => setPhoneIdInput(event.target.value)}
                      placeholder="tel-001"
                      pattern="tel-[0-9]{3}"
                      required
                      disabled={Boolean(editingPhoneId)}
                    />
                  </label>

                  <label>
                    Nom du téléphone
                    <input
                      type="text"
                      value={phoneNameInput}
                      onChange={(event) => setPhoneNameInput(event.target.value)}
                      maxLength={100}
                      required
                    />
                  </label>

                  <label>
                    Nom du compte ntfy associé (facultatif)
                    <input
                      type="text"
                      value={phoneUsernameInput}
                      onChange={(event) => setPhoneUsernameInput(event.target.value)}
                      maxLength={32}
                      placeholder="tel001"
                    />
                  </label>

                  <label>
                    Statut
                    <select
                      value={phoneStatusInput}
                      onChange={(event) =>
                        setPhoneStatusInput(event.target.value as "active" | "disabled")
                      }
                    >
                      <option value="active">Actif</option>
                      <option value="disabled">Désactivé</option>
                    </select>
                  </label>

                  <label>
                    Notes (facultatif)
                    <textarea
                      value={phoneNotesInput}
                      onChange={(event) => setPhoneNotesInput(event.target.value)}
                      maxLength={1000}
                      rows={3}
                    />
                  </label>

                  <button type="submit" disabled={phoneActionLoading}>
                    {phoneActionLoading ? "Enregistrement…" : "Enregistrer"}
                  </button>
                  <button
                    type="button"
                    disabled={phoneActionLoading}
                    onClick={() => {
                      setShowPhoneForm(false);
                      setEditingPhoneId("");
                      setPhoneActionError("");
                    }}
                  >
                    Annuler
                  </button>
                </form>
              )}

                            {phonesLoading ? (
                <p>Chargement de l’inventaire…</p>
              ) : (
                <>
                  <div className="phone-filters">
                    <label>
                      Rechercher un téléphone
                      <input
                        type="search"
                        value={phoneSearch}
                        onChange={(event) => setPhoneSearch(event.target.value)}
                        placeholder="Identifiant, nom, compte ntfy ou notes"
                      />
                    </label>

                    <label>
                      Filtrer par statut
                      <select
                        value={phoneStatusFilter}
                        onChange={(event) =>
                          setPhoneStatusFilter(
                            event.target.value as "all" | "active" | "disabled"
                          )
                        }
                      >
                        <option value="all">Tous les statuts</option>
                        <option value="active">Actifs</option>
                        <option value="disabled">Désactivés</option>
                      </select>
                    </label>
                  </div>

                  {phones.length === 0 ? (
                    <p>Aucun téléphone enregistré pour le moment.</p>
                  ) : (

               <div className="table-container">
                  <table>
                    <thead>
                      <tr>
                        <th>Identifiant</th>
                        <th>Nom</th>
                        <th>Compte ntfy</th>
                        <th>Statut</th>
                        <th>Notes</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredPhones.map((phone) => (
                        <tr key={phone.phone_id}>
                          <td>{phone.phone_id}</td>
                          <td>{phone.name}</td>
                          <td>{phone.ntfy_username || "—"}</td>
                          <td>
                            {phone.status === "active" ? "Actif" : "Désactivé"}
                          </td>
                          <td>{phone.notes || "—"}</td>
                          <td>
                            <button
                              type="button"
                              disabled={phoneActionLoading}
                              onClick={() => handleEditPhone(phone)}
                            >
                              Modifier
                            </button>
                            <button
                              type="button"
                              disabled={phoneActionLoading}
                              onClick={() => void handleDeletePhone(phone)}
                            >
                              Retirer
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
		</>
              )}
            </section>
          ) : active === "Intérimaires" ? (
            <section className="panel phone-inventory-panel interim-panel">
              <div className="panel-heading">
                <div>
                  <h2>Gestion des intérimaires</h2>
                  <p>Suivi des missions et des échéances des comptes ntfy associés.</p>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setEditingInterimWorkerId(null);
                    setInterimFullName("");
                    setInterimUsername("");
                    setInterimStartDate("");
                    setInterimEndDate("");
                    setInterimPhoneIds([]);
                    setInterimMessage("");
                    setInterimError("");
                    setShowInterimForm(true);
                  }}
                >
                  Ajouter un intérimaire
                </button>
              </div>

              {interimError && <p role="alert">{interimError}</p>}
              {interimMessage && <p role="status">{interimMessage}</p>}

              {showInterimForm && (
                <form
                  className="account-form"
                  onSubmit={editingInterimWorkerId ? handleUpdateInterimWorker : handleSaveInterimWorker}
                >
                  <h3>{editingInterimWorkerId ? "Modifier la fiche intérimaire" : "Nouvel intérimaire"}</h3>

                  <label>
                    Nom complet
                    <input
                      type="text"
                      value={interimFullName}
                      onChange={(event) => setInterimFullName(event.target.value)}
                      maxLength={150}
                      required
                    />
                  </label>

                  {!editingInterimWorkerId && (
                    <label>
                      Nom d’utilisateur ntfy existant
                      <input
                        type="text"
                        value={interimUsername}
                        onChange={(event) => setInterimUsername(event.target.value)}
                        maxLength={32}
                        pattern="[a-zA-Z0-9_-]+"
                        required
                      />
                    </label>
                  )}

                  <label>
                    Date de début
                    <input
                      type="date"
                      value={interimStartDate}
                      onChange={(event) => setInterimStartDate(event.target.value)}
                      required
                    />
                  </label>

                  <label>
                    Date de fin
                    <input
                      type="date"
                      value={interimEndDate}
                      min={interimStartDate || undefined}
                      onChange={(event) => setInterimEndDate(event.target.value)}
                      required
                    />
                  </label>

                  <fieldset>
                    <legend>Téléphones associés</legend>
                    {phones.length === 0 ? (
                      <p>Aucun téléphone dans l’inventaire.</p>
                    ) : (
                      phones.map((phone) => (
                        <label key={phone.phone_id}>
                          <input
                            type="checkbox"
                            checked={interimPhoneIds.includes(phone.phone_id)}
                            onChange={(event) => {
                              setInterimPhoneIds((current) =>
                                event.target.checked
                                  ? [...current, phone.phone_id]
                                  : current.filter((id) => id !== phone.phone_id)
                              );
                            }}
                          />
                          {phone.phone_id} — {phone.name}
                        </label>
                      ))
                    )}
                  </fieldset>

                  <div className="form-actions">
                    <button type="submit" disabled={interimActionLoading}>
                      {interimActionLoading
                        ? "Enregistrement…"
                        : editingInterimWorkerId
                          ? "Enregistrer les modifications"
                          : "Créer la fiche"}
                    </button>
                    <button
                      type="button"
                      disabled={interimActionLoading}
                      onClick={() => {
                        setShowInterimForm(false);
                        setEditingInterimWorkerId(null);
                      }}
                    >
                      Annuler
                    </button>
                  </div>
                </form>
              )}

              {interimLoading ? (
                <p>Chargement des intérimaires…</p>
              ) : interimWorkers.length === 0 ? (
                <p>Aucune fiche intérimaire enregistrée pour le moment.</p>
              ) : (
                <div className="table-container">
                  <table>
                    <thead>
                      <tr>
                        <th>Nom</th>
                        <th>Compte ntfy</th>
                        <th>Début</th>
                        <th>Fin</th>
                        <th>Téléphones</th>
                        <th>Échéance</th>
                        <th>Décision</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {interimWorkers.map((worker) => (
                        <tr key={worker.id}>
                          <td>{worker.full_name}</td>
                          <td>{worker.ntfy_username}</td>
                          <td>{worker.start_date}</td>
                          <td>{worker.end_date}</td>
                          <td>
                            {worker.phones.length
                              ? worker.phones.map((phone) => phone.phone_id).join(", ")
                              : "—"}
                          </td>
                          <td>
                            {worker.alert === "overdue"
                              ? "Échéance dépassée"
                              : worker.alert === "due_today"
                                ? "Échéance aujourd’hui"
                                : worker.alert === "closed"
                                  ? "Fiche clôturée"
                                  : "En cours"}
                          </td>
                          <td>
                            {worker.decision === "extended"
                              ? "Prolongation enregistrée"
                              : worker.decision === "keep_access"
                                ? "Accès conservé"
                                : worker.decision === "access_reviewed"
                                  ? "Accès réexaminé"
                                  : "À examiner"}
                            {worker.decision_note && <p>{worker.decision_note}</p>}
                          </td>
                          <td>
                            {worker.status === "closed" ? (
                              <span>Fiche clôturée</span>
                            ) : (
                              <div className="form-actions">
                                <button
                                  type="button"
                                  disabled={interimActionLoading}
                                  onClick={() => handleEditInterimWorker(worker)}
                                >
                                  Modifier la fiche
                                </button>
                                <label>
                                  Décision
                                  <select
                                    value={interimDecisionChoices[worker.id] ?? worker.decision}
                                    disabled={interimActionLoading}
                                    onChange={(event) =>
                                      setInterimDecisionChoices((current) => ({
                                        ...current,
                                        [worker.id]: event.target.value as InterimWorker["decision"],
                                      }))
                                    }
                                  >
                                    <option value="pending">À examiner</option>
                                    <option value="extended">Prolongation</option>
                                    <option value="access_reviewed">Accès réexaminé</option>
                                    <option value="keep_access">Conserver l’accès</option>
                                  </select>
                                </label>
                                <label>
                                  Note
                                  <input
                                    value={interimDecisionNotes[worker.id] ?? ""}
                                    disabled={interimActionLoading}
                                    onChange={(event) =>
                                      setInterimDecisionNotes((current) => ({
                                        ...current,
                                        [worker.id]: event.target.value,
                                      }))
                                    }
                                    maxLength={1000}
                                    placeholder="Note facultative"
                                  />
                                </label>
                                <button
                                  type="button"
                                  disabled={interimActionLoading}
                                  onClick={() =>
                                    void handleInterimAction(
                                      worker,
                                      "decision",
                                      interimDecisionChoices[worker.id] ?? worker.decision
                                    )
                                  }
                                >
                                  Enregistrer
                                </button>
                                <button
                                  type="button"
                                  disabled={interimActionLoading}
                                  onClick={() => void handleInterimAction(worker, "close")}
                                >
                                  Clôturer la mission
                                </button>
                              </div>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          ) : active === "Historique" ? (
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <h2>Historique des opérations</h2>
                  <p>Les 100 événements les plus récents enregistrés par l’application</p>
                </div>
                <button
                  type="button"
                  onClick={() => setActive("Vue d’ensemble")}
                >
                  Retour
                </button>
              </div>

              {auditLoading ? (
                <p>Chargement de l’historique…</p>
              ) : auditError ? (
                <p role="alert">{auditError}</p>
              ) : auditEvents.length === 0 ? (
                <p>Aucun événement enregistré pour le moment.</p>
              ) : (
                <div className="table-wrapper">
                  <table>
                    <thead>
                      <tr>
                        <th>Date</th>
                        <th>Utilisateur</th>
                        <th>Action</th>
                        <th>Cible</th>
                        <th>Détails</th>
                      </tr>
                    </thead>
                    <tbody>
                      {auditEvents.map((event) => (
                        <tr key={event.id}>
                          <td>{new Date(event.created_at).toLocaleString("fr-FR")}</td>
                          <td>{event.actor_username}</td>
                          <td>{event.action}</td>
                          <td>
                            {[event.target_type, event.target_id]
                              .filter(Boolean)
                              .join(" · ") || "—"}
                          </td>
                          <td>{event.details_json || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          ) : active === "Notifications" ? (
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <h2>Préparer une notification</h2>
                  <p>Choisissez les téléphones actifs et vérifiez le message avant tout envoi.</p>
                </div>
              </div>

              {phonesLoading ? (
                <p>Chargement des téléphones…</p>
              ) : phonesError ? (
                <p role="alert">{phonesError}</p>
              ) : (
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    setNotificationPreview(true);
                  }}
                >
                  <fieldset>
                    <legend>Destinataires ({notificationRecipients.length} sélectionnés)</legend>
                    <div className="notification-recipient-list">
                      {phones.filter((phone) => phone.status === "active").map((phone) => (
                        <label key={phone.phone_id}>
                          <input
                            type="checkbox"
                            checked={notificationRecipients.includes(phone.phone_id)}
                            onChange={(event) => {
                              setNotificationPreview(false);
                              setNotificationRecipients((current) =>
                                event.target.checked
                                  ? [...current, phone.phone_id]
                                  : current.filter((id) => id !== phone.phone_id)
                              );
                            }}
                          />
                          {phone.name} ({phone.phone_id})
                        </label>
                      ))}
                    </div>
                    {phones.filter((phone) => phone.status === "active").length === 0 && (
                      <p>Aucun téléphone actif enregistré.</p>
                    )}
                  </fieldset>

                  <label htmlFor="notification-title">Titre</label>
                  <input
                    id="notification-title"
                    value={notificationTitle}
                    maxLength={120}
                    required
                    onChange={(event) => {
                      setNotificationTitle(event.target.value);
                      setNotificationPreview(false);
                    }}
                  />

                  <label htmlFor="notification-body">Message</label>
                  <textarea
                    id="notification-body"
                    value={notificationBody}
                    rows={5}
                    maxLength={4000}
                    required
                    onChange={(event) => {
                      setNotificationBody(event.target.value);
                      setNotificationPreview(false);
                    }}
                  />

                  <button
                    type="submit"
                    className="add-account-button"
                    disabled={notificationRecipients.length === 0 || !notificationTitle.trim() || !notificationBody.trim()}
                  >
                    Prévisualiser
                  </button>
                </form>
              )}

              {notificationPreview && (
                <div className="notification-preview" aria-live="polite">
                  <h3>Aperçu — aucun message envoyé</h3>
                  <p><strong>Destinataires :</strong> {notificationRecipients.map((id) => {
                    const phone = phones.find((item) => item.phone_id === id);
                    return phone ? `${phone.name} (${phone.phone_id})` : id;
                  }).join(", ")}</p>
                  <p><strong>Titre :</strong> {notificationTitle}</p>
                  <p><strong>Message :</strong></p>
                  <p>{notificationBody}</p>
                  <button
                    type="button"
                    onClick={() => setNotificationPreview(false)}
                    disabled={notificationSending}
                  >
                    Modifier le brouillon
                  </button>
                  <button
                    type="button"
                    className="add-account-button"
                    onClick={() => void handleSendNotification()}
                    disabled={notificationSending}
                  >
                    {notificationSending ? "Envoi en cours…" : "Envoyer la notification"}
                  </button>
                </div>
              )}

              {notificationResult && (
                <p role="status" aria-live="polite">{notificationResult}</p>
              )}
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
