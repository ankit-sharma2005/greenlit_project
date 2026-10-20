import { FormEvent, useEffect, useRef, useState } from 'react';
import {
  Link,
  Navigate,
  NavLink,
  Route,
  Routes,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router-dom';
import { apiRequest, User, Workspace } from './api';
import WorkspaceProjects from './WorkspaceProjects';
import { AssistantPanel } from './WorkspaceChat';

const features = [
  {
    title: 'Workspace-ready',
    description:
      'From prompt to launch verdict, every run is rooted in a workspace and an audit trail.',
  },
  {
    title: 'Offline evals',
    description:
      'Evaluate a staging copy with a fixed golden dataset, not live user traffic.',
  },
  {
    title: 'Safety first',
    description:
      'Guardrails, canaries, and red-team payloads are built into the evaluation flow.',
  },
];

interface AuthenticatedUser {
  accessToken: string;
  user: User;
  workspaces: Workspace[];
}

interface WorkspaceProjectOption {
  id: string;
  name: string;
}

const workspacePages = [
  ['overview', 'Overview'],
  ['providers', 'LLM Providers'],
  ['projects', 'Projects'],
  ['connector', 'Project Connector'],
  ['dataset', 'Dataset Studio'],
  ['evaluation', 'Evaluation Runs'],
  ['results', 'Results/Reports'],
  ['test-chat', 'Test Chat'],
  ['settings', 'Settings'],
] as const;

type WorkspacePageId = (typeof workspacePages)[number][0];

const pageSet = new Set<string>(workspacePages.map(([id]) => id));

function ThemeToggle() {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    const savedTheme = localStorage.getItem('greenlit-theme');
    return savedTheme === 'light' ? 'light' : 'dark';
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('greenlit-theme', theme);
  }, [theme]);

  return (
    <button
      className="theme-toggle"
      type="button"
      onClick={() =>
        setTheme((current) => (current === 'dark' ? 'light' : 'dark'))
      }
      aria-label="Toggle color theme"
    >
      {theme === 'dark' ? 'Light mode' : 'Dark mode'}
    </button>
  );
}

function Brand() {
  return (
    <div className="brand">
      <span className="brand-mark">G</span>
      <span>GreenLit</span>
    </div>
  );
}

function LandingPage() {
  return (
    <div className="page-shell">
      <header className="topbar">
        <Brand />
        <nav className="nav">
          <NavLink to="/" end>
            Product
          </NavLink>
          <NavLink to="/login">Login</NavLink>
          <NavLink to="/signup">Signup</NavLink>
        </nav>
        <ThemeToggle />
      </header>

      <main className="hero">
        <div className="hero-copy">
          <p className="eyebrow">OFFLINE LLM APP EVALUATION</p>
          <h1>Launch decisions grounded in evidence, not vibes.</h1>
          <p className="lede">
            GreenLit helps teams test RAG, chatbots, agents, and extraction
            workflows against the same golden dataset and launch criteria before
            production.
          </p>
          <div className="hero-actions">
            <Link to="/signup" className="primary-button">
              Create workspace
            </Link>
            <Link to="/login" className="secondary-button">
              Sign in
            </Link>
          </div>
          <div className="stats-row">
            <div>
              <strong>GO / NO_GO</strong>
              <span>launch verdict</span>
            </div>
            <div>
              <strong>Quality + safety</strong>
              <span>hard gates</span>
            </div>
            <div>
              <strong>Regression checks</strong>
              <span>same suite</span>
            </div>
          </div>
        </div>
        <div className="hero-panel">
          <div className="panel-card">
            <div className="panel-header">
              <span className="status-dot" />
              <span>Evaluation workflow</span>
            </div>
            <ol className="workflow-list">
              <li>Define task and launch criteria</li>
              <li>Build a fixed golden dataset</li>
              <li>Run, inspect, and decide</li>
            </ol>
            <p className="verdict verdict-good">
              Repeatable evaluations for safer launches
            </p>
          </div>
        </div>
      </main>

      <section className="feature-grid">
        {features.map((feature) => (
          <article key={feature.title} className="feature-card">
            <h3>{feature.title}</h3>
            <p>{feature.description}</p>
          </article>
        ))}
      </section>
    </div>
  );
}

function AuthPage({
  mode,
  onAuthenticated,
}: {
  mode: 'login' | 'signup';
  onAuthenticated: (session: AuthenticatedUser) => void;
}) {
  const isLogin = mode === 'login';
  const navigate = useNavigate();
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setIsSubmitting(true);

    const formData = new FormData(event.currentTarget);
    const credentials = {
      email: String(formData.get('email') ?? ''),
      password: String(formData.get('password') ?? ''),
    };

    try {
      const endpoint = isLogin ? '/auth/login' : '/auth/signup';
      const body = isLogin
        ? credentials
        : {
            ...credentials,
            workspace_name: String(formData.get('workspace_name') ?? ''),
          };
      const result = await apiRequest<{ access_token: string }>(endpoint, {
        method: 'POST',
        body: JSON.stringify(body),
      });
      const [user, workspaces] = await Promise.all([
        apiRequest<User>('/auth/me', {}, result.access_token),
        apiRequest<Workspace[]>('/workspaces', {}, result.access_token),
      ]);
      onAuthenticated({ accessToken: result.access_token, user, workspaces });
      navigate('/workspace');
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'Unable to sign in. Please try again.',
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="page-shell auth-page">
      <header className="topbar compact-topbar">
        <Brand />
        <ThemeToggle />
      </header>

      <main className="auth-shell">
        <aside className="auth-brand-panel">
          <p className="eyebrow">BUILD CONFIDENCE</p>
          <h2>Run a fixed evaluation suite before launch.</h2>
          <ul>
            <li>Golden dataset gating</li>
            <li>Safety canaries and policy checks</li>
            <li>Regression capture across prompt and retrieval changes</li>
          </ul>
        </aside>

        <section
          className="auth-card"
          aria-label={isLogin ? 'Login form' : 'Signup form'}
        >
          <div className="auth-tabs">
            <Link to="/login" className={isLogin ? 'active' : ''}>
              Login
            </Link>
            <Link to="/signup" className={!isLogin ? 'active' : ''}>
              Signup
            </Link>
          </div>
          <h1>{isLogin ? 'Welcome back' : 'Create your workspace'}</h1>
          <form onSubmit={handleSubmit}>
            <label>
              <span>Email</span>
              <input
                name="email"
                type="email"
                autoComplete="email"
                placeholder="name@company.com"
                required
              />
            </label>
            <label>
              <span>Password</span>
              <input
                name="password"
                type="password"
                autoComplete={isLogin ? 'current-password' : 'new-password'}
                minLength={8}
                required
              />
            </label>
            {!isLogin && (
              <label>
                <span>Workspace name</span>
                <input
                  name="workspace_name"
                  type="text"
                  placeholder="Acme evals"
                  required
                />
              </label>
            )}
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
            <button
              type="submit"
              className="primary-button full-width"
              disabled={isSubmitting}
            >
              {isSubmitting
                ? 'Please wait…'
                : isLogin
                  ? 'Sign in'
                  : 'Create workspace'}
            </button>
          </form>
          {isLogin && (
            <Link className="forgot-password-link" to="/reset-password">
              Forgot password?
            </Link>
          )}
        </section>
      </main>
    </div>
  );
}

function PasswordResetPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage('');
    setError('');
    setIsSubmitting(true);
    const formData = new FormData(event.currentTarget);

    try {
      if (token) {
        await apiRequest<{ ok: boolean }>('/auth/password-reset/confirm', {
          method: 'POST',
          body: JSON.stringify({
            token,
            password: String(formData.get('password') ?? ''),
          }),
        });
        setMessage(
          'Password updated. You can now sign in with your new password.',
        );
      } else {
        await apiRequest<{ ok: boolean; message: string }>(
          '/auth/password-reset/request',
          {
            method: 'POST',
            body: JSON.stringify({
              email: String(formData.get('email') ?? ''),
            }),
          },
        );
        setMessage('If the account exists, reset instructions have been sent.');
      }
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'Unable to reset the password.',
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="page-shell auth-page">
      <header className="topbar compact-topbar">
        <Brand />
        <ThemeToggle />
      </header>
      <main className="auth-shell">
        <section
          className="auth-card reset-card"
          aria-label="Password reset form"
        >
          <p className="eyebrow">ACCOUNT RECOVERY</p>
          <h1>{token ? 'Choose a new password' : 'Reset your password'}</h1>
          <form onSubmit={handleSubmit}>
            {token ? (
              <label>
                <span>New password</span>
                <input
                  name="password"
                  type="password"
                  autoComplete="new-password"
                  minLength={8}
                  required
                />
              </label>
            ) : (
              <label>
                <span>Email</span>
                <input
                  name="email"
                  type="email"
                  autoComplete="email"
                  placeholder="name@company.com"
                  required
                />
              </label>
            )}
            {message && (
              <p className="success-message" role="status">
                {message}
              </p>
            )}
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
            <button
              className="primary-button full-width"
              type="submit"
              disabled={isSubmitting}
            >
              {isSubmitting
                ? 'Please wait…'
                : token
                  ? 'Update password'
                  : 'Send reset instructions'}
            </button>
          </form>
          <Link className="forgot-password-link" to="/login">
            Back to login
          </Link>
        </section>
      </main>
    </div>
  );
}

function WorkspacePage({
  session,
  onLogout,
}: {
  session: AuthenticatedUser;
  onLogout: () => Promise<void>;
}) {
  const [error, setError] = useState('');
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isAssistantOpen, setIsAssistantOpen] = useState(false);
  const [projectOptions, setProjectOptions] = useState<
    WorkspaceProjectOption[]
  >([]);
  const [activeProjectId, setActiveProjectId] = useState('');
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState(
    session.workspaces[0]?.id ?? '',
  );
  const { page: pageParam } = useParams<{ page?: string }>();
  const navigate = useNavigate();
  const selectedWorkspace = session.workspaces.find(
    (workspace) => workspace.id === selectedWorkspaceId,
  );
  const page = (
    pageSet.has(pageParam ?? '') ? pageParam : 'overview'
  ) as WorkspacePageId;
  const pageTitle =
    workspacePages.find(([id]) => id === page)?.[1] ?? 'Overview';

  useEffect(() => {
    if (!selectedWorkspaceId) return;
    let isCurrent = true;
    void Promise.all([
      apiRequest<WorkspaceProjectOption[]>(
        `/workspaces/${encodeURIComponent(selectedWorkspaceId)}/projects`,
        {},
        session.accessToken,
      ),
      apiRequest<{ active_project_id: string | null }>(
        `/workspaces/${encodeURIComponent(selectedWorkspaceId)}/preferences`,
        {},
        session.accessToken,
      ),
    ])
      .then(([projects, preferences]) => {
        if (!isCurrent) return;
        setProjectOptions(projects);
        const activeId =
          projects.find(
            (project) => project.id === preferences.active_project_id,
          )?.id ??
          projects[0]?.id ??
          '';
        setActiveProjectId(activeId);
      })
      .catch((reason: unknown) => {
        if (!isCurrent) return;
        setProjectOptions([]);
        setActiveProjectId('');
        setError(
          reason instanceof Error
            ? `Project switcher could not load: ${reason.message}`
            : 'Project switcher could not load.',
        );
      });
    return () => {
      isCurrent = false;
    };
  }, [selectedWorkspaceId, session.accessToken]);

  useEffect(() => {
    if (!selectedWorkspaceId) return;
    if (pageParam && !pageSet.has(pageParam)) {
      navigate('/workspace/overview', { replace: true });
      return;
    }
    if (pageParam) return;

    let isCurrent = true;
    void apiRequest<{ last_page?: string }>(
      `/workspaces/${encodeURIComponent(selectedWorkspaceId)}/preferences`,
      {},
      session.accessToken,
    )
      .then((preferences) => {
        const destination =
          preferences.last_page && pageSet.has(preferences.last_page)
            ? preferences.last_page
            : 'overview';
        if (isCurrent) {
          navigate(`/workspace/${destination}`, { replace: true });
        }
      })
      .catch(() => {
        if (isCurrent) navigate('/workspace/overview', { replace: true });
      });
    return () => {
      isCurrent = false;
    };
  }, [navigate, pageParam, selectedWorkspaceId, session.accessToken]);

  async function handleLogout() {
    setError('');
    setIsLoggingOut(true);
    try {
      await onLogout();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : 'Unable to sign out.',
      );
    } finally {
      setIsLoggingOut(false);
    }
  }

  return (
    <div className="page-shell dashboard-shell">
      <header className="topbar">
        <button
          className="sidebar-toggle secondary-button"
          type="button"
          aria-expanded={isSidebarOpen}
          aria-controls="workspace-sidebar"
          onClick={() => setIsSidebarOpen((current) => !current)}
        >
          Menu
        </button>
        <Brand />
        <div className="workspace-crumb" aria-label="Breadcrumb">
          {selectedWorkspace?.name ?? 'Workspace'} <span>/</span> {pageTitle}
        </div>
        <div className="header-actions">
          <label className="topbar-project-switcher" title="Active project">
            <span className="sr-only">Active project</span>
            <select
              aria-label="Active project"
              value={activeProjectId}
              disabled={!projectOptions.length}
              onChange={(event) => {
                const projectId = event.target.value;
                setActiveProjectId(projectId);
                if (!selectedWorkspaceId) return;
                void apiRequest(
                  `/workspaces/${encodeURIComponent(selectedWorkspaceId)}/preferences`,
                  {
                    method: 'PUT',
                    body: JSON.stringify({
                      active_project_id: projectId || null,
                    }),
                  },
                  session.accessToken,
                ).catch((reason: unknown) => {
                  setError(
                    reason instanceof Error
                      ? `Could not save the active project: ${reason.message}`
                      : 'Could not save the active project.',
                  );
                });
              }}
            >
              <option value="">Select a project</option>
              {projectOptions.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>
          <button
            className="secondary-button"
            type="button"
            onClick={() => setIsAssistantOpen(true)}
          >
            GreenLit Assistant
          </button>
          <ThemeToggle />
          <span className="user-menu-label">{session.user.email}</span>
          <button
            className="secondary-button"
            type="button"
            onClick={handleLogout}
            disabled={isLoggingOut}
          >
            {isLoggingOut ? 'Signing out…' : 'Sign out'}
          </button>
        </div>
      </header>
      <div className="workspace-layout">
        <aside
          id="workspace-sidebar"
          className={`workspace-sidebar ${isSidebarOpen ? 'open' : ''}`}
          aria-label="Workspace navigation"
        >
          <label className="workspace-switcher">
            <span>Workspace</span>
            <select
              value={selectedWorkspaceId}
              onChange={(event) => setSelectedWorkspaceId(event.target.value)}
            >
              {session.workspaces.map((workspace) => (
                <option key={workspace.id} value={workspace.id}>
                  {workspace.name}
                </option>
              ))}
            </select>
          </label>
          <nav className="workspace-nav">
            {workspacePages.map(([id, label]) => (
              <NavLink
                key={id}
                to={`/workspace/${id}`}
                className={({ isActive }) =>
                  isActive ? 'workspace-nav-link active' : 'workspace-nav-link'
                }
                onClick={() => setIsSidebarOpen(false)}
              >
                {label}
              </NavLink>
            ))}
          </nav>
        </aside>
        <main className="workspace-content">
          <div className="workspace-header-block">
            <p className="eyebrow">WORKSPACE · {pageTitle.toUpperCase()}</p>
            <h1>
              {selectedWorkspace?.name ?? 'Workspace'} · {pageTitle}
            </h1>
          </div>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          {session.workspaces.length === 0 ? (
            <section className="dashboard-card">
              <h2>No workspaces found</h2>
              <p className="muted-text">
                Your account has no workspace memberships.
              </p>
            </section>
          ) : null}
          {selectedWorkspace && pageParam && pageSet.has(pageParam) ? (
            <WorkspaceProjects
              key={`${session.user.id}-${selectedWorkspace.id}`}
              accessToken={session.accessToken}
              userRole={session.user.role}
              userId={session.user.id}
              workspace={selectedWorkspace}
              page={page}
              activeProjectId={activeProjectId}
              onProjectOptionsChange={setProjectOptions}
              onActiveProjectChange={setActiveProjectId}
            />
          ) : (
            <p className="muted-text" role="status">
              Restoring your last workspace page…
            </p>
          )}
          {isAssistantOpen && selectedWorkspace && (
            <AssistantPanel
              accessToken={session.accessToken}
              workspace={selectedWorkspace}
              onClose={() => setIsAssistantOpen(false)}
            />
          )}
        </main>
      </div>
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState<AuthenticatedUser | null>(null);
  const [isBootstrapping, setIsBootstrapping] = useState(true);
  const [sessionExpired, setSessionExpired] = useState(false);
  const navigate = useNavigate();
  const didBootstrap = useRef(false);

  useEffect(() => {
    const onTokenRefreshed = (event: Event) => {
      const detail = (event as CustomEvent<{ accessToken?: string }>).detail;
      if (detail?.accessToken) {
        const accessToken = detail.accessToken;
        setSession((current) =>
          current ? { ...current, accessToken } : current,
        );
      }
    };
    const onAuthExpired = () => {
      setSession(null);
      setSessionExpired(true);
      navigate('/login', { replace: true });
    };
    window.addEventListener('greenlit:token-refreshed', onTokenRefreshed);
    window.addEventListener('greenlit:auth-expired', onAuthExpired);
    return () => {
      window.removeEventListener('greenlit:token-refreshed', onTokenRefreshed);
      window.removeEventListener('greenlit:auth-expired', onAuthExpired);
    };
  }, [navigate]);

  useEffect(() => {
    if (didBootstrap.current) return;
    didBootstrap.current = true;

    async function restoreSession() {
      try {
        const refreshed = await apiRequest<{ access_token: string }>(
          '/auth/refresh',
          { method: 'POST' },
        );
        const [user, workspaces] = await Promise.all([
          apiRequest<User>('/auth/me', {}, refreshed.access_token),
          apiRequest<Workspace[]>('/workspaces', {}, refreshed.access_token),
        ]);
        setSession({ accessToken: refreshed.access_token, user, workspaces });
      } catch {
        setSession(null);
      } finally {
        setIsBootstrapping(false);
      }
    }

    void restoreSession();
  }, []);

  async function logout() {
    if (!session) return;
    await apiRequest<{ ok: boolean }>(
      '/auth/logout',
      { method: 'POST' },
      session.accessToken,
    );
    setSession(null);
  }

  if (isBootstrapping) {
    return (
      <main className="loading-screen" aria-live="polite">
        Restoring your GreenLit session…
      </main>
    );
  }

  return (
    <>
      {sessionExpired && (
        <div className="phase2-alert phase2-alert-error" role="alert">
          Session expired, please log in again
        </div>
      )}
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route
          path="/login"
          element={
            session ? (
              <Navigate to="/workspace" replace />
            ) : (
              <AuthPage mode="login" onAuthenticated={setSession} />
            )
          }
        />
        <Route
          path="/signup"
          element={
            session ? (
              <Navigate to="/workspace" replace />
            ) : (
              <AuthPage mode="signup" onAuthenticated={setSession} />
            )
          }
        />
        <Route path="/reset-password" element={<PasswordResetPage />} />
        <Route
          path="/workspace/:page?"
          element={
            session ? (
              <WorkspacePage session={session} onLogout={logout} />
            ) : (
              <Navigate to="/login" replace />
            )
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}
