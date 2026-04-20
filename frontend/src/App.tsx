import { useState, useEffect } from 'react';
import Split from 'react-split';
import { SymbolTree } from './components/SymbolTree';
import { CodeViewer } from './components/CodeViewer';
import { GraphViewer } from './components/GraphViewer';
import { Phase2Viewer } from './components/Phase2Viewer';
import { Hero } from './components/Hero';
import './App.css';

type WorkspacePhase = 'phase1' | 'phase2';

async function fetchJsonFromPaths(paths: string[]): Promise<any> {
  let lastError: unknown = null;
  for (const path of paths) {
    try {
      const response = await fetch(path);
      if (!response.ok) {
        lastError = new Error(`HTTP ${response.status} for ${path}`);
        continue;
      }
      return await response.json();
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError ?? new Error('Unable to load JSON artifacts');
}

function App() {
  const [selectedRepo, setSelectedRepo] = useState<string>('pilot-repo-1');
  const [activePhase, setActivePhase] = useState<WorkspacePhase>('phase1');
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [sdgData, setSdgData] = useState<any>(null);
  const [phase2Report, setPhase2Report] = useState<any>(null);
  const [phase2LoadError, setPhase2LoadError] = useState<string | null>(null);
  const [workspaceActive, setWorkspaceActive] = useState<boolean>(false);

  useEffect(() => {
    if (selectedRepo) {
      fetchJsonFromPaths(['/artifacts/phase1/sdg_v1.json', '/artifacts/sdg_v1.json'])
        .then(data => {
          setSdgData(data);
        })
        .catch(err => {
          console.error('Error loading SDG data:', err);
          setSdgData(null);
        });

      fetchJsonFromPaths(['/artifacts/phase2/report.json'])
        .then(data => {
          setPhase2Report(data);
          setPhase2LoadError(null);
        })
        .catch(err => {
          console.warn('Phase 2 report not available:', err);
          setPhase2Report(null);
          setPhase2LoadError(
            'Phase 2 artifacts not found. Run phase 2 pipeline and sync artifacts to frontend/public/artifacts/phase2.'
          );
        });
    }
  }, [selectedRepo]);

  if (!workspaceActive) {
    return (
      <div className="app-container">
        <header className="header">
          <div className="brand glitch" data-text="Cartographer">Cartographer <span style={{fontSize: '12px', fontWeight: 'normal'}}>v1.0.0</span></div>
        </header>
        <div className="hero-page-wrapper">
          <Hero onLocalScanStart={() => setWorkspaceActive(true)} />
        </div>
      </div>
    );
  }

  return (
    <div className="app-container">
      <header className="header">
        <div className="brand glitch" data-text="Cartographer">Cartographer <span style={{fontSize: '12px', fontWeight: 'normal'}}>v1.0.0</span></div>
        <div className="header-controls">
          <div className="phase-chip">{activePhase === 'phase1' ? 'PHASE 1' : 'PHASE 2'}</div>
          <select
            className="select-repo"
            value={selectedRepo}
            onChange={(e) => setSelectedRepo(e.target.value)}
          >
            <option value="pilot-repo-1">Pilot Repo 1</option>
            <option value="sys-demo">System Demo</option>
          </select>
          <button
            className="cyber-btn phase-nav-btn"
            onClick={() => {
              setSelectedSymbol(null);
              setActivePhase(activePhase === 'phase1' ? 'phase2' : 'phase1');
            }}
          >
            {activePhase === 'phase1' ? 'Next Phase' : 'Back to Phase 1'}
          </button>
          <button className="cyber-btn" onClick={() => setWorkspaceActive(false)}>Back to Home</button>
        </div>
      </header>

      {activePhase === 'phase1' ? (
        <div className="main-content">
          <aside className="sidebar">
            <div className="panel-header">Symbol Index</div>
            <SymbolTree sdgData={sdgData} selectedSymbol={selectedSymbol} onSelectSymbol={setSelectedSymbol} />
          </aside>

          <main className="workspace">
            <Split
              sizes={[40, 60]}
              minSize={250}
              gutterSize={6}
              className="split-flex"
              direction="horizontal"
            >
              <CodeViewer selectedSymbol={selectedSymbol} sdgData={sdgData} />
              <GraphViewer selectedSymbol={selectedSymbol} sdgData={sdgData} onSelectSymbol={setSelectedSymbol} />
            </Split>
          </main>
        </div>
      ) : (
        <div className="main-content phase2-layout">
          <Phase2Viewer reportData={phase2Report} loadError={phase2LoadError} sdgData={sdgData} />
        </div>
      )}
    </div>
  );
}

export default App;
