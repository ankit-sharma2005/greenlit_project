import { FormEvent, useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiRequest, Workspace } from './api';

interface Conversation {
  id: string;
  kind: 'assistant' | 'project';
  title: string;
  project_id: string | null;
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  context_sent: Array<Record<string, unknown>>;
  trace: Record<string, unknown>;
}

interface AssistantPanelProps {
  accessToken: string;
  workspace: Workspace;
  onClose: () => void;
}

interface ProjectTestChatProps {
  accessToken: string;
  workspace: Workspace;
  projectId: string;
  connectorType: string | null;
}

function workspacePath(workspaceId: string, path: string) {
  return `/workspaces/${encodeURIComponent(workspaceId)}${path}`;
}

function formatContext(context: Array<Record<string, unknown>>) {
  return JSON.stringify(context, null, 2);
}

export function AssistantPanel({
  accessToken,
  workspace,
  onClose,
}: AssistantPanelProps) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState('');
  const [loadedMessages, setLoadedMessages] = useState<{
    conversationId: string;
    messages: ChatMessage[];
  } | null>(null);
  const messages =
    loadedMessages?.conversationId === conversationId
      ? loadedMessages.messages
      : [];
  const [search, setSearch] = useState('');
  const [content, setContent] = useState('');
  const [memory, setMemory] = useState<{
    summary_used: boolean;
    messages_in_context: number;
    message_limit: number;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');

  const loadConversations = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const result = await apiRequest<Conversation[]>(
        workspacePath(
          workspace.id,
          `/chat/conversations?kind=assistant&search=${encodeURIComponent(search)}`,
        ),
        {},
        accessToken,
      );
      setConversations(result);
      if (conversationId && result.some((item) => item.id === conversationId)) {
        return;
      }
      setConversationId(result[0]?.id ?? '');
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'Assistant conversations could not be loaded.',
      );
    } finally {
      setLoading(false);
    }
  }, [accessToken, conversationId, search, workspace.id]);

  useEffect(() => {
    void Promise.resolve().then(loadConversations);
  }, [loadConversations]);

  useEffect(() => {
    if (!conversationId) return;
    let current = true;
    void apiRequest<ChatMessage[]>(
      workspacePath(
        workspace.id,
        `/chat/conversations/${encodeURIComponent(conversationId)}/messages`,
      ),
      {},
      accessToken,
    )
      .then((result) => {
        if (current) setLoadedMessages({ conversationId, messages: result });
      })
      .catch((reason: unknown) => {
        if (current) {
          setError(
            reason instanceof Error
              ? reason.message
              : 'Conversation history could not be loaded.',
          );
        }
      });
    return () => {
      current = false;
    };
  }, [accessToken, conversationId, workspace.id]);

  async function newConversation() {
    setError('');
    try {
      const created = await apiRequest<Conversation>(
        workspacePath(workspace.id, '/chat/conversations'),
        {
          method: 'POST',
          body: JSON.stringify({ kind: 'assistant', title: 'New chat' }),
        },
        accessToken,
      );
      setConversations((items) => [created, ...items]);
      setLoadedMessages({ conversationId: created.id, messages: [] });
      setConversationId(created.id);
      setMemory(null);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'A new assistant conversation could not be created.',
      );
    }
  }

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (sending || !content.trim()) return;
    setSending(true);
    setError('');
    try {
      let selectedId = conversationId;
      if (!selectedId) {
        const created = await apiRequest<Conversation>(
          workspacePath(workspace.id, '/chat/conversations'),
          {
            method: 'POST',
            body: JSON.stringify({ kind: 'assistant', title: 'New chat' }),
          },
          accessToken,
        );
        selectedId = created.id;
        setConversationId(selectedId);
        setConversations((items) => [created, ...items]);
      }
      const result = await apiRequest<{
        user_message: ChatMessage;
        assistant_message: ChatMessage;
        memory: {
          summary_used: boolean;
          messages_in_context: number;
          message_limit: number;
        };
      }>(
        workspacePath(
          workspace.id,
          `/assistant/conversations/${encodeURIComponent(selectedId)}/messages`,
        ),
        {
          method: 'POST',
          body: JSON.stringify({ content: content.trim() }),
          signal: AbortSignal.timeout(90_000),
        },
        accessToken,
      );
      setLoadedMessages((current) => ({
        conversationId: selectedId,
        messages: [
          ...(current?.conversationId === selectedId ? current.messages : []),
          result.user_message,
          result.assistant_message,
        ],
      }));
      setMemory(result.memory);
      setContent('');
      void loadConversations();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'GreenLit Assistant could not answer this message.',
      );
    } finally {
      setSending(false);
    }
  }

  async function renameConversation(item: Conversation) {
    const title = window.prompt('Rename conversation', item.title)?.trim();
    if (!title || title === item.title) return;
    try {
      const updated = await apiRequest<Conversation>(
        workspacePath(
          workspace.id,
          `/chat/conversations/${encodeURIComponent(item.id)}`,
        ),
        { method: 'PATCH', body: JSON.stringify({ title }) },
        accessToken,
      );
      setConversations((items) =>
        items.map((current) => (current.id === updated.id ? updated : current)),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Rename failed.');
    }
  }

  async function deleteConversation(item: Conversation) {
    if (!window.confirm(`Delete "${item.title}" and its messages?`)) return;
    try {
      await apiRequest(
        workspacePath(
          workspace.id,
          `/chat/conversations/${encodeURIComponent(item.id)}`,
        ),
        { method: 'DELETE' },
        accessToken,
      );
      setConversations((items) =>
        items.filter((current) => current.id !== item.id),
      );
      if (conversationId === item.id) {
        setConversationId('');
        setLoadedMessages(null);
      }
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'Conversation deletion failed.',
      );
    }
  }

  async function clearHistory() {
    if (
      !window.confirm('Delete all of your GreenLit Assistant chat history?')
    ) {
      return;
    }
    try {
      await apiRequest(
        workspacePath(workspace.id, '/chat/data'),
        { method: 'DELETE' },
        accessToken,
      );
      setConversations([]);
      setConversationId('');
      setLoadedMessages(null);
      setMemory(null);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'Chat history deletion failed.',
      );
    }
  }

  return (
    <aside
      className="assistant-panel"
      role="dialog"
      aria-label="GreenLit Assistant"
    >
      <header className="chat-panel-header">
        <div>
          <p className="eyebrow">WORKSPACE HELP</p>
          <h2>GreenLit Assistant</h2>
        </div>
        <button
          className="secondary-button"
          type="button"
          onClick={onClose}
          aria-label="Close GreenLit Assistant"
        >
          Close
        </button>
      </header>
      <div className="chat-panel-controls">
        <button
          className="secondary-button"
          type="button"
          onClick={newConversation}
        >
          New chat
        </button>
        <label>
          <span className="sr-only">Search conversations</span>
          <input
            type="search"
            placeholder="Search history"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
      </div>
      <div
        className="chat-conversation-list"
        aria-label="Assistant conversations"
      >
        {conversations.map((item) => (
          <div className="chat-conversation-row" key={item.id}>
            <button
              type="button"
              className={item.id === conversationId ? 'selected' : ''}
              onClick={() => setConversationId(item.id)}
            >
              {item.title}
            </button>
            <button
              type="button"
              aria-label={`Rename ${item.title}`}
              onClick={() => void renameConversation(item)}
            >
              Rename
            </button>
            <button
              type="button"
              aria-label={`Delete ${item.title}`}
              onClick={() => void deleteConversation(item)}
            >
              Delete
            </button>
          </div>
        ))}
      </div>
      <div className="chat-message-list" aria-live="polite">
        {loading ? <p role="status">Loading chat history…</p> : null}
        {messages.map((message) => (
          <article className={`chat-message ${message.role}`} key={message.id}>
            <strong>
              {message.role === 'assistant' ? 'Assistant' : 'You'}
            </strong>
            <p>{message.content}</p>
          </article>
        ))}
        {!messages.length && !loading ? (
          <p className="muted-text">
            Ask about setup, datasets, connectors, evaluation runs, or an error.
          </p>
        ) : null}
      </div>
      {memory && (
        <p className="chat-memory-indicator" role="status">
          Memory: {memory.messages_in_context}/{memory.message_limit} recent
          messages
          {memory.summary_used ? ' · older messages summarized' : ''}
        </p>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}{' '}
          {error.toLowerCase().includes('provider') ? (
            <Link to="/workspace/providers">Open LLM Providers</Link>
          ) : null}
        </p>
      )}
      <form className="chat-send-form" onSubmit={sendMessage}>
        <label>
          <span className="sr-only">Message GreenLit Assistant</span>
          <textarea
            value={content}
            onChange={(event) => setContent(event.target.value)}
            rows={3}
            maxLength={20_000}
            placeholder="Ask GreenLit Assistant…"
          />
        </label>
        <button
          className="primary-button"
          type="submit"
          disabled={sending || !content.trim()}
        >
          {sending ? 'Sending…' : 'Send'}
        </button>
      </form>
      <button
        className="text-button"
        type="button"
        onClick={() => void clearHistory()}
      >
        Delete my chat data
      </button>
    </aside>
  );
}

export function ProjectTestChat({
  accessToken,
  workspace,
  projectId,
  connectorType,
}: ProjectTestChatProps) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState('');
  const [loadedMessages, setLoadedMessages] = useState<{
    conversationId: string;
    messages: ChatMessage[];
  } | null>(null);
  const messages =
    loadedMessages?.conversationId === conversationId
      ? loadedMessages.messages
      : [];
  const [search, setSearch] = useState('');
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [addingDraftId, setAddingDraftId] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const liveChatAvailable =
    projectId.length > 0 &&
    connectorType !== null &&
    connectorType !== 'UPLOAD_OUTPUTS';

  const loadConversations = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const result = await apiRequest<Conversation[]>(
        workspacePath(
          workspace.id,
          `/chat/conversations?kind=project&search=${encodeURIComponent(search)}`,
        ),
        {},
        accessToken,
      );
      const projectSessions = result.filter(
        (item) => item.project_id === projectId,
      );
      setConversations(projectSessions);
      if (!projectSessions.some((item) => item.id === conversationId)) {
        setConversationId(projectSessions[0]?.id ?? '');
      }
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'Test Chat sessions could not be loaded.',
      );
    } finally {
      setLoading(false);
    }
  }, [accessToken, conversationId, projectId, search, workspace.id]);

  useEffect(() => {
    void Promise.resolve().then(loadConversations);
  }, [loadConversations]);

  useEffect(() => {
    if (!conversationId) return;
    let current = true;
    void apiRequest<ChatMessage[]>(
      workspacePath(
        workspace.id,
        `/chat/conversations/${encodeURIComponent(conversationId)}/messages`,
      ),
      {},
      accessToken,
    )
      .then((result) => {
        if (current) setLoadedMessages({ conversationId, messages: result });
      })
      .catch((reason: unknown) => {
        if (current) {
          setError(
            reason instanceof Error
              ? reason.message
              : 'Test Chat history could not be loaded.',
          );
        }
      });
    return () => {
      current = false;
    };
  }, [accessToken, conversationId, workspace.id]);

  async function createConversation() {
    setError('');
    try {
      const created = await apiRequest<Conversation>(
        workspacePath(workspace.id, '/chat/conversations'),
        {
          method: 'POST',
          body: JSON.stringify({
            kind: 'project',
            project_id: projectId,
            title: 'New test session',
          }),
        },
        accessToken,
      );
      setConversations((items) => [created, ...items]);
      setConversationId(created.id);
      setLoadedMessages({ conversationId: created.id, messages: [] });
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'A Test Chat session could not be created.',
      );
    }
  }

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!conversationId || sending || !content.trim()) return;
    setSending(true);
    setError('');
    try {
      const result = await apiRequest<{
        user_message: ChatMessage;
        assistant_message: ChatMessage;
        context_sent: Array<Record<string, unknown>>;
      }>(
        workspacePath(
          workspace.id,
          `/projects/${encodeURIComponent(projectId)}/test-chat/conversations/${encodeURIComponent(conversationId)}/messages`,
        ),
        {
          method: 'POST',
          body: JSON.stringify({ content: content.trim() }),
          signal: AbortSignal.timeout(150_000),
        },
        accessToken,
      );
      setLoadedMessages((current) => ({
        conversationId,
        messages: [
          ...(current?.conversationId === conversationId
            ? current.messages
            : []),
          result.user_message,
          result.assistant_message,
        ],
      }));
      setContent('');
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : 'The test chat call failed.',
      );
    } finally {
      setSending(false);
    }
  }

  async function renameConversation(item: Conversation) {
    const title = window.prompt('Rename test session', item.title)?.trim();
    if (!title || title === item.title) return;
    try {
      const updated = await apiRequest<Conversation>(
        workspacePath(
          workspace.id,
          `/chat/conversations/${encodeURIComponent(item.id)}`,
        ),
        { method: 'PATCH', body: JSON.stringify({ title }) },
        accessToken,
      );
      setConversations((items) =>
        items.map((current) => (current.id === updated.id ? updated : current)),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Rename failed.');
    }
  }

  async function deleteConversation(item: Conversation) {
    if (!window.confirm(`Delete "${item.title}" and its messages?`)) return;
    try {
      await apiRequest(
        workspacePath(
          workspace.id,
          `/chat/conversations/${encodeURIComponent(item.id)}`,
        ),
        { method: 'DELETE' },
        accessToken,
      );
      setConversations((items) =>
        items.filter((current) => current.id !== item.id),
      );
      if (conversationId === item.id) {
        setConversationId('');
        setLoadedMessages(null);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Delete failed.');
    }
  }

  async function addToDataset(assistantMessageId?: string) {
    if (!conversationId || addingDraftId) return;
    const lockId = assistantMessageId ?? 'session';
    setAddingDraftId(lockId);
    setNotice('');
    setError('');
    try {
      const result = await apiRequest<{
        dataset_version?: number;
        created_items: number;
      }>(
        workspacePath(
          workspace.id,
          `/projects/${encodeURIComponent(projectId)}/test-chat/conversations/${encodeURIComponent(conversationId)}/draft-items`,
        ),
        {
          method: 'POST',
          body: JSON.stringify(
            assistantMessageId
              ? { assistant_message_id: assistantMessageId }
              : {},
          ),
        },
        accessToken,
      );
      setNotice(
        result.created_items
          ? `${result.created_items} draft item(s) added to Dataset Studio. They still need human approval.`
          : 'These turns are already in the draft dataset.',
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'The draft dataset could not be updated.',
      );
    } finally {
      setAddingDraftId('');
    }
  }

  return (
    <section className="dashboard-card phase2-card test-chat-page">
      <div className="phase2-section-heading">
        <div>
          <p className="eyebrow">PROJECT CONVERSATIONS</p>
          <h2>Test Chat</h2>
        </div>
        {liveChatAvailable && (
          <button
            className="primary-button"
            type="button"
            onClick={createConversation}
          >
            New session
          </button>
        )}
      </div>
      {!liveChatAvailable ? (
        <div className="phase2-alert">
          {!projectId ? (
            <>Select or create a project before starting Test Chat.</>
          ) : !connectorType ? (
            <>
              Test and save a project connector first on the{' '}
              <Link to="/workspace/connector">Project Connector page</Link>.
            </>
          ) : (
            <>
              Live chat is not possible for an UPLOAD_OUTPUTS connector. Use the
              sample-input lookup instead on the{' '}
              <Link to="/workspace/connector">Project Connector page</Link>.
            </>
          )}
        </div>
      ) : (
        <>
          <div
            className="chat-conversation-list"
            aria-label="Test Chat sessions"
          >
            <label className="chat-session-search">
              <span className="sr-only">Search Test Chat sessions</span>
              <input
                type="search"
                placeholder="Search sessions"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>
            {conversations.map((item) => (
              <div className="chat-conversation-row" key={item.id}>
                <button
                  type="button"
                  className={item.id === conversationId ? 'selected' : ''}
                  onClick={() => setConversationId(item.id)}
                >
                  {item.title}
                </button>
                <button
                  type="button"
                  aria-label={`Rename ${item.title}`}
                  onClick={() => void renameConversation(item)}
                >
                  Rename
                </button>
                <button
                  type="button"
                  aria-label={`Delete ${item.title}`}
                  onClick={() => void deleteConversation(item)}
                >
                  Delete
                </button>
              </div>
            ))}
            {!loading && !conversations.length ? (
              <p className="muted-text">No saved test sessions yet.</p>
            ) : null}
          </div>
          {conversationId && (
            <button
              className="secondary-button"
              type="button"
              disabled={Boolean(addingDraftId)}
              onClick={() => void addToDataset()}
            >
              {addingDraftId === 'session'
                ? 'Adding session…'
                : 'Add this session to golden dataset (draft)'}
            </button>
          )}
          <div className="chat-message-list" aria-live="polite">
            {messages.map((message) => (
              <article
                className={`chat-message ${message.role}`}
                key={message.id}
              >
                <strong>{message.role === 'assistant' ? 'App' : 'You'}</strong>
                <p>{message.content}</p>
                {message.role === 'user' && message.context_sent.length > 0 ? (
                  <details>
                    <summary>Exact context sent</summary>
                    <pre>{formatContext(message.context_sent)}</pre>
                  </details>
                ) : null}
                {message.role === 'assistant' &&
                Object.keys(message.trace).length > 0 ? (
                  <details>
                    <summary>Retrieved context, tools, and usage</summary>
                    <pre>{JSON.stringify(message.trace, null, 2)}</pre>
                  </details>
                ) : null}
                {message.role === 'assistant' ? (
                  <button
                    className="secondary-button"
                    type="button"
                    disabled={Boolean(addingDraftId)}
                    onClick={() => void addToDataset(message.id)}
                  >
                    {addingDraftId === message.id
                      ? 'Adding…'
                      : 'Add to golden dataset (draft)'}
                  </button>
                ) : null}
              </article>
            ))}
          </div>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          {notice && (
            <p className="success-message" role="status">
              {notice}
            </p>
          )}
          {loading ? <p role="status">Loading test sessions…</p> : null}
          <form className="chat-send-form" onSubmit={sendMessage}>
            <label>
              <span className="sr-only">Message the connected app</span>
              <textarea
                value={content}
                onChange={(event) => setContent(event.target.value)}
                rows={3}
                maxLength={20_000}
                placeholder="Send a message to the connected app…"
                disabled={!conversationId || sending}
              />
            </label>
            <button
              className="primary-button"
              type="submit"
              disabled={!conversationId || sending || !content.trim()}
            >
              {sending ? 'Sending…' : 'Send'}
            </button>
          </form>
        </>
      )}
    </section>
  );
}
