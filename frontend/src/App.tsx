import { useState, useEffect } from 'react';
import Split from 'react-split';
import { SymbolTree } from './components/SymbolTree';
import { CodeViewer } from './components/CodeViewer';
import { GraphViewer } from './components/GraphViewer';
import { Hero } from './components/Hero';
import './App.css';

function App() {
  const [selectedRepo, setSelectedRepo] = useState<string>('pilot-repo-1');
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [sdgData, setSdgData] = useState<any>(null);
  const [workspaceActive, setWorkspaceActive] = useState<boolean>(false);

  useEffect(() => {
    if (selectedRepo) {
      fetch('/artifacts/phase1/sdg_v1.json')
        .then(res => res.json())
        .then(data => {
          console.log("Loaded data:", data);
          setSdgData(data);
        })
        .catch(err => {
          console.error("Error loading SDG data:", err);
          // Try alternative path if serving from root
          fetch('/artifacts/sdg_v1.json')
            .then(res => res.json())
            .then(data => setSdgData(data))
            .catch(e => console.error("Failed alternative load:", e));
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
        <div style={{display: 'flex', alignItems: 'center', gap: '15px'}}>
          <select 
            className="select-repo"
            value={selectedRepo}
            onChange={(e) => setSelectedRepo(e.target.value)}
          >
            <option value="pilot-repo-1">Pilot Repo 1</option>
            <option value="sys-demo">System Demo</option>
          </select>
          <button className="cyber-btn" onClick={() => setWorkspaceActive(false)}>Back to Home</button>
        </div>
      </header>

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
    </div>
  );
}

export default App;
