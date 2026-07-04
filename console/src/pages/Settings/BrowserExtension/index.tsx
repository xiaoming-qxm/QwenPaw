import { useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { Button, Spin } from "antd";
import { ChevronDown, Copy, RefreshCw } from "lucide-react";
import {
  extensionApi,
  type ExtensionInstallMode,
  type ExtensionStatus,
} from "@/api/modules/extension";
import { useAppMessage } from "@/hooks/useAppMessage";
import { BrowserControlReadiness } from "../browserControlReadiness";

const CWS_FALLBACK_URL =
  "https://chromewebstore.google.com/detail/qwenpaw-browser-bridge/nflcgkfjgoiipklkpenmbiificbakoch";

const pageStyle: CSSProperties = {
  minHeight: "100%",
  padding: 24,
  background: "#f7f8fa",
};

const shellStyle: CSSProperties = {
  width: "min(100%, 860px)",
  margin: "0 auto",
  display: "flex",
  flexDirection: "column",
  gap: 16,
};

const panelStyle: CSSProperties = {
  border: "1px solid rgba(0,0,0,0.08)",
  borderRadius: 8,
  background: "#fff",
  padding: 24,
};

const rowListStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 10,
};

const codeStyle: CSSProperties = {
  fontFamily:
    "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
  fontSize: 12,
  overflowWrap: "anywhere",
};

function currentBridgeWsUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/nm-bridge`;
}

function cwsUrl(status: ExtensionStatus | null) {
  return status?.cws_url || CWS_FALLBACK_URL;
}

function DeveloperOptions({
  open,
  status,
  setupLoading,
  onCopy,
  onRegenerate,
  onToggle,
}: {
  open: boolean;
  status: ExtensionStatus | null;
  setupLoading: boolean;
  onCopy: (value: string) => void;
  onRegenerate: () => void;
  onToggle: () => void;
}) {
  const rows = [
    ["Extension folder", status?.extension_dir],
    ["Native manifest", status?.native_manifest_path],
    ["Native host", status?.native_host_path],
    ["Bridge config", status?.config_path],
    ["Bridge endpoint", status?.ws_url || currentBridgeWsUrl()],
  ].filter(([, value]) => Boolean(value));

  return (
    <div style={panelStyle}>
      <button
        onClick={onToggle}
        style={{
          width: "100%",
          border: 0,
          background: "transparent",
          padding: 0,
          display: "flex",
          alignItems: "center",
          gap: 8,
          font: "inherit",
          fontWeight: 600,
          cursor: "pointer",
          textAlign: "left",
        }}
      >
        Advanced Setup
        <ChevronDown
          size={16}
          style={{
            marginLeft: "auto",
            transform: open ? "rotate(180deg)" : "none",
          }}
        />
      </button>
      {open ? (
        <div style={{ ...rowListStyle, marginTop: 16 }}>
          {rows.map(([label, value]) => (
            <div
              key={label}
              style={{
                display: "grid",
                gridTemplateColumns: "150px minmax(0, 1fr) auto",
                gap: 8,
                alignItems: "center",
              }}
            >
              <span style={{ color: "rgba(0,0,0,0.58)" }}>{label}</span>
              <code style={codeStyle}>{value}</code>
              <Button
                aria-label={`Copy ${label}`}
                icon={<Copy size={14} />}
                onClick={() => onCopy(String(value))}
              />
            </div>
          ))}
          <div>
            <Button loading={setupLoading} onClick={onRegenerate}>
              Regenerate Files
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function BrowserExtensionPage() {
  const { message } = useAppMessage();
  const [status, setStatus] = useState<ExtensionStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [setupLoading, setSetupLoading] = useState(false);
  const [selfTestLoading, setSelfTestLoading] = useState(false);
  const [developerOpen, setDeveloperOpen] = useState(false);
  const [showTips, setShowTips] = useState(false);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    try {
      const next = await extensionApi.getStatus();
      setStatus(next);
      return next;
    } catch (err) {
      message.error(err instanceof Error ? err.message : String(err));
      return null;
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const installed = Boolean(status?.installed);
  const connected = Boolean(status?.connected);

  useEffect(() => {
    if (!installed || connected) {
      setShowTips(false);
      return undefined;
    }

    const pollId = window.setInterval(() => {
      void loadStatus();
    }, 3000);
    const tipsId = window.setTimeout(() => setShowTips(true), 10000);

    return () => {
      window.clearInterval(pollId);
      window.clearTimeout(tipsId);
    };
  }, [connected, installed, loadStatus]);

  const setup = useCallback(
    async (
      installMode: ExtensionInstallMode,
      reset: boolean,
    ): Promise<ExtensionStatus | null> => {
      setSetupLoading(true);
      try {
        const next = await extensionApi.setup({
          install_mode: installMode,
          reset,
          ws_url: currentBridgeWsUrl(),
        });
        setStatus(next);
        return next;
      } catch (err) {
        message.error(err instanceof Error ? err.message : String(err));
        return null;
      } finally {
        setSetupLoading(false);
      }
    },
    [message],
  );

  const handleInstallCws = async () => {
    const next = await setup("cws", false);
    window.open(cwsUrl(next || status), "_blank", "noopener,noreferrer");
  };

  const handleRegenerate = async () => {
    await setup("unpacked", false);
  };

  const handleCopy = async (value: string) => {
    await navigator.clipboard?.writeText(value);
    message.success("Copied");
  };

  const handleCopyDiagnostics = async () => {
    await handleCopy(JSON.stringify(status ?? {}, null, 2));
  };

  const handleOpenChrome = async () => {
    try {
      const result = await extensionApi.openChromeExtensionsPage();
      if (!result.opened && result.url) {
        await handleCopy(result.url);
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : String(err));
    }
  };

  const handleRunSelfTest = async () => {
    setSelfTestLoading(true);
    try {
      const result = await extensionApi.selfTest();
      setStatus((current) =>
        current ? { ...current, last_self_test: result } : current,
      );
      message.success("Self-test complete");
    } catch (err) {
      message.error(err instanceof Error ? err.message : String(err));
    } finally {
      setSelfTestLoading(false);
    }
  };

  const content = useMemo(() => {
    if (loading && !status) {
      return (
        <div style={{ ...panelStyle, textAlign: "center" }}>
          <Spin />
        </div>
      );
    }

    if (connected) {
      return (
        <div style={panelStyle}>
          <h1 style={{ marginTop: 0 }}>Browser Bridge Active</h1>
          <div style={rowListStyle}>
            <div>Open the current browser page and summarize it.</div>
            <div>Click the next actionable button on this page.</div>
            <div>Collect the visible product prices into a table.</div>
          </div>
          <Button
            icon={<RefreshCw size={14} />}
            loading={loading}
            onClick={() => void loadStatus()}
            style={{ marginTop: 16 }}
          >
            Refresh Status
          </Button>
        </div>
      );
    }

    if (installed) {
      return (
        <div style={panelStyle}>
          <h1 style={{ marginTop: 0 }}>Waiting for Chrome to connect</h1>
          <p style={{ color: "rgba(0,0,0,0.62)" }}>
            Open or reload the QwenPaw browser extension in Chrome. This page
            checks the bridge every 3 seconds.
          </p>
          <Button loading={loading} onClick={() => void loadStatus()}>
            Refresh Status
          </Button>
          {showTips ? (
            <div
              style={{
                marginTop: 16,
                border: "1px solid rgba(250,173,20,0.42)",
                borderRadius: 8,
                padding: 12,
                background: "rgba(250,173,20,0.12)",
              }}
            >
              <strong>Still not connected?</strong>
              <ul style={{ marginBottom: 0 }}>
                <li>Make sure Developer mode is enabled.</li>
                <li>Click the QwenPaw extension icon in Chrome once.</li>
                <li>Reload the extension or reopen the target browser tab.</li>
              </ul>
            </div>
          ) : null}
        </div>
      );
    }

    return (
      <div style={{ ...panelStyle, textAlign: "center" }}>
        <h1 style={{ marginTop: 0 }}>Browser Control</h1>
        <p style={{ color: "rgba(0,0,0,0.62)" }}>
          Connect QwenPaw to Chrome through the local browser bridge.
        </p>
        <div
          style={{
            display: "flex",
            gap: 12,
            justifyContent: "center",
            flexWrap: "wrap",
          }}
        >
          <Button
            type="primary"
            loading={setupLoading}
            onClick={() => void handleInstallCws()}
          >
            Install from Chrome Web Store
          </Button>
          <Button type="link" onClick={() => setDeveloperOpen(true)}>
            Developer Options
          </Button>
        </div>
      </div>
    );
  }, [
    connected,
    installed,
    loadStatus,
    loading,
    setupLoading,
    showTips,
    status,
  ]);

  return (
    <div style={pageStyle}>
      <div style={shellStyle}>
        {content}
        <BrowserControlReadiness
          loading={loading}
          onCopyDiagnostics={() => void handleCopyDiagnostics()}
          onOpenChrome={() => void handleOpenChrome()}
          onRefresh={() => void loadStatus()}
          onRunSelfTest={() => void handleRunSelfTest()}
          selfTestLoading={selfTestLoading}
          status={status}
        />
        <DeveloperOptions
          onCopy={(value) => void handleCopy(value)}
          onRegenerate={() => void handleRegenerate()}
          onToggle={() => setDeveloperOpen((value) => !value)}
          open={developerOpen}
          setupLoading={setupLoading}
          status={status}
        />
      </div>
    </div>
  );
}
