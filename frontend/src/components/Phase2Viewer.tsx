import { useState } from 'react';
import Split from 'react-split';
import CytoscapeComponent from 'react-cytoscapejs';

interface Phase2ViewerProps {
  reportData: any;
  loadError: string | null;
  sdgData?: any;
}

function valueOrDash(value: unknown): string {
  if (value === undefined || value === null) {
    return '-';
  }
  return String(value);
}

export function Phase2Viewer({ reportData, loadError, sdgData }: Phase2ViewerProps) {
  const [selectedItem, setSelectedItem] = useState<any>(null);
  const [activeTab, setActiveTab] = useState<'tasks' | 'code' | 'obligations'>('tasks');

  if (!reportData) {
    return (
      <div className="phase2-viewer-empty">
        <h2 className="section-title">Phase 2 Orchestration</h2>
        <p className="phase2-message">
          {loadError || 'Phase 2 report is not loaded yet.'}
        </p>
      </div>
    );
  }

  const plan = reportData.plan || {};
  const metrics = reportData.metrics || {};
  const obligations = reportData.obligations || {};
  const tasks = reportData.tasks || [];
  const batches = Array.isArray(plan.batches) ? plan.batches : [];
  const closedObligations = Array.isArray(obligations.closed) ? obligations.closed : [];

  // Build Graph Elements (Batches + Functions)
  const elements: any[] = [];
  const allFunctionIds = new Set<string>();

  // Add Batch Compound Nodes & Function Nodes
  batches.forEach((batch: any) => {
    // Add the batch as a parent node
    elements.push({
      data: {
        id: `batch-${batch.index}`,
        label: `Batch ${batch.index}`,
        type: 'batch',
        batchData: batch
      },
      classes: 'batch-node'
    });

    // Add function nodes inside this batch
    if (batch.function_node_ids && batch.function_names) {
      batch.function_node_ids.forEach((fnId: string, idx: number) => {
        allFunctionIds.add(fnId);
        elements.push({
          data: {
            id: fnId,
            label: batch.function_names[idx],
            parent: `batch-${batch.index}`,
            type: 'function',
            batchData: batch
          },
          classes: 'function-node'
        });
      });
    }
  });

  // Add Edges from SDG (Function Calls)
  let hasRealEdges = false;
  if (sdgData && Array.isArray(sdgData.edges)) {
    sdgData.edges.forEach((edge: any, index: number) => {
      if (
        edge.edge_type === 'calls' && 
        allFunctionIds.has(edge.source) && 
        allFunctionIds.has(edge.target)
      ) {
        hasRealEdges = true;
        elements.push({
          data: {
            id: `call-${index}`,
            source: edge.source,
            target: edge.target
          },
          classes: 'call-edge'
        });
      }
    });
  }

  // Fallback to linear batch connections if no real edges exist
  if (!hasRealEdges) {
    batches.forEach((batch: any, index: number) => {
      if (index > 0) {
        elements.push({
          data: {
            id: `edge-${index - 1}-${index}`,
            source: `batch-${batches[index - 1].index}`,
            target: `batch-${batch.index}`
          },
          classes: 'fallback-edge'
        });
      }
    });
  }

  const cyStylesheet = [
    {
      selector: '.batch-node',
      style: {
        'background-color': 'rgba(15, 23, 42, 0.5)',
        'border-width': 1,
        'border-color': '#475569',
        'border-style': 'dashed',
        'label': 'data(label)',
        'color': '#94a3b8',
        'text-valign': 'top',
        'text-halign': 'center',
        'font-size': '14px',
        'font-family': 'monospace',
        'padding': '20px'
      }
    },
    {
      selector: '.function-node',
      style: {
        'background-color': '#0f172a',
        'border-width': 2,
        'border-color': '#38bdf8',
        'label': 'data(label)',
        'color': '#e2e8f0',
        'text-valign': 'center',
        'text-halign': 'center',
        'font-size': '11px',
        'font-family': 'monospace',
        'text-wrap': 'wrap',
        'width': 'label',
        'height': '30px',
        'padding': '10px',
        'shape': 'roundrectangle'
      }
    },
    {
      selector: 'node:selected',
      style: {
        'background-color': '#0369a1',
        'border-color': '#7dd3fc',
        'border-width': 3,
      }
    },
    {
      selector: '.call-edge',
      style: {
        'width': 2,
        'line-color': '#6366f1',
        'target-arrow-color': '#6366f1',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier'
      }
    },
    {
      selector: '.fallback-edge',
      style: {
        'width': 2,
        'line-color': '#475569',
        'target-arrow-color': '#475569',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        'line-style': 'dashed'
      }
    }
  ];

  const handleNodeClick = (event: any) => {
    const node = event.target;
    setSelectedItem(node.data('batchData'));
  };

  const layout = {
    name: 'breadthfirst',
    directed: true,
    padding: 30,
    spacingFactor: 1.5,
    avoidOverlap: true
  };

  return (
    <div className="phase2-viewer" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <section className="phase2-summary-grid" style={{ flexShrink: 0, marginBottom: '16px' }}>
        <article className="phase2-summary-card">
          <div className="phase2-label">Batches</div>
          <div className="phase2-value">{valueOrDash(plan.batch_count)}</div>
        </article>
        <article className="phase2-summary-card">
          <div className="phase2-label">Tasks</div>
          <div className="phase2-value">{valueOrDash(metrics.total_tasks)}</div>
        </article>
        <article className="phase2-summary-card">
          <div className="phase2-label">Successful</div>
          <div className="phase2-value" style={{ color: '#4ade80' }}>{valueOrDash(metrics.successful_tasks)}</div>
        </article>
        <article className="phase2-summary-card">
          <div className="phase2-label">Failed</div>
          <div className="phase2-value" style={{ color: '#f87171' }}>{valueOrDash(metrics.failed_tasks)}</div>
        </article>
        <article className="phase2-summary-card">
          <div className="phase2-label">Repair Loops</div>
          <div className="phase2-value">{valueOrDash(metrics.repair_loops)}</div>
        </article>
        <article className="phase2-summary-card">
          <div className="phase2-label">Open Obligations</div>
          <div className="phase2-value" style={{ color: obligations.open_count > 0 ? '#facc15' : '#4ade80' }}>{valueOrDash(obligations.open_count)}</div>
        </article>
      </section>

      <Split
        sizes={[50, 50]}
        minSize={300}
        gutterSize={6}
        className="split-flex"
        direction="horizontal"
        style={{ flexGrow: 1, display: 'flex', minHeight: 0 }}
      >
        <div className="phase2-panel" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
          <div className="panel-header">Function Dependency Graph</div>
          <div style={{ flexGrow: 1, position: 'relative', background: '#020617' }}>
            <CytoscapeComponent
              elements={elements}
              stylesheet={cyStylesheet as any}
              layout={layout}
              style={{ width: '100%', height: '100%' }}
              cy={(cy) => {
                cy.on('tap', 'node', handleNodeClick);
              }}
            />
          </div>
        </div>

        <div className="phase2-panel" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
          <div className="panel-header" style={{ display: 'flex', gap: '16px' }}>
            <span 
              style={{ cursor: 'pointer', color: activeTab === 'tasks' ? '#38bdf8' : '#94a3b8' }}
              onClick={() => setActiveTab('tasks')}
            >
              Execution Logs
            </span>
            <span 
              style={{ cursor: 'pointer', color: activeTab === 'code' ? '#38bdf8' : '#94a3b8' }}
              onClick={() => setActiveTab('code')}
            >
              Translated Code
            </span>
            <span 
              style={{ cursor: 'pointer', color: activeTab === 'obligations' ? '#38bdf8' : '#94a3b8' }}
              onClick={() => setActiveTab('obligations')}
            >
              Obligations
            </span>
          </div>
          
          <div className="phase2-scrollable" style={{ flexGrow: 1, overflowY: 'auto', padding: '16px' }}>
            {activeTab === 'tasks' && (
              <>
                {selectedItem ? (
                  <div style={{ marginBottom: '16px', padding: '12px', background: '#0f172a', borderLeft: '4px solid #38bdf8' }}>
                    <h3 style={{ margin: '0 0 8px 0', fontSize: '14px', color: '#e2e8f0' }}>Filtering by Batch {selectedItem.index}</h3>
                    <p style={{ margin: 0, fontSize: '12px', color: '#94a3b8' }}>
                      Functions: {(selectedItem.function_names || []).join(', ')}
                    </p>
                  </div>
                ) : (
                  <div style={{ marginBottom: '16px', fontSize: '12px', color: '#94a3b8' }}>
                    Select a node in the graph to filter logs. Showing all logs.
                  </div>
                )}
                
                {tasks.length === 0 ? (
                  <div className="phase2-message">No tasks recorded.</div>
                ) : (
                  tasks
                    .filter((t: any) => !selectedItem || t.batch_index === selectedItem.index)
                    .map((task: any, i: number) => (
                    <div key={i} style={{ marginBottom: '16px', background: '#0f172a', borderRadius: '6px', overflow: 'hidden', border: `1px solid ${task.runtime_success && task.validation_success ? '#065f46' : '#7f1d1d'}` }}>
                      <div style={{ padding: '8px 12px', background: 'rgba(255,255,255,0.05)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <strong style={{ fontSize: '13px', color: '#e2e8f0' }}>{task.function_name}</strong>
                        <span style={{ fontSize: '11px', padding: '2px 6px', borderRadius: '4px', background: task.runtime_success && task.validation_success ? '#064e3b' : '#450a0a', color: task.runtime_success && task.validation_success ? '#a7f3d0' : '#fecaca' }}>
                          Attempt {task.attempt}
                        </span>
                      </div>
                      <div style={{ padding: '12px', fontSize: '12px', color: '#cbd5e1' }}>
                        <div style={{ marginBottom: '4px' }}><span style={{ color: '#94a3b8' }}>ID:</span> {task.task_id}</div>
                        <div style={{ marginBottom: '4px' }}><span style={{ color: '#94a3b8' }}>Reason:</span> {task.reason}</div>
                        <div style={{ marginBottom: '4px' }}>
                          <span style={{ color: '#94a3b8' }}>Metrics:</span> {task.metrics?.latency_ms}ms, {task.metrics?.token_usage} tokens
                        </div>
                        {task.interface_changes && task.interface_changes.length > 0 && (
                          <div style={{ marginTop: '8px' }}>
                            <strong style={{ color: '#38bdf8' }}>Interface Changes:</strong>
                            <pre style={{ margin: '4px 0 0 0', padding: '8px', background: '#020617', borderRadius: '4px', fontSize: '11px', overflowX: 'auto' }}>
                              {JSON.stringify(task.interface_changes, null, 2)}
                            </pre>
                          </div>
                        )}
                        {task.diagnostics && task.diagnostics.length > 0 && (
                          <div style={{ marginTop: '8px' }}>
                            <strong style={{ color: '#f87171' }}>Diagnostics:</strong>
                            <ul style={{ margin: '4px 0 0 0', paddingLeft: '20px' }}>
                              {task.diagnostics.map((diag: string, idx: number) => (
                                <li key={idx} style={{ color: '#fca5a5' }}>{diag}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </>
            )}

            {activeTab === 'code' && (
              <>
                {selectedItem ? (
                  <div style={{ marginBottom: '16px', padding: '12px', background: '#0f172a', borderLeft: '4px solid #38bdf8' }}>
                    <h3 style={{ margin: '0 0 8px 0', fontSize: '14px', color: '#e2e8f0' }}>Filtering by Batch {selectedItem.index}</h3>
                  </div>
                ) : (
                  <div style={{ marginBottom: '16px', fontSize: '12px', color: '#94a3b8' }}>
                    Select a node in the graph to filter translated code. Showing all translated functions.
                  </div>
                )}
                
                {tasks.length === 0 ? (
                  <div className="phase2-message">No code translations recorded.</div>
                ) : (
                  tasks
                    .filter((t: any) => !selectedItem || t.batch_index === selectedItem.index)
                    .filter((t: any) => t.translated_artifact) // Only show tasks with translations
                    .map((task: any, i: number) => (
                    <div key={i} style={{ marginBottom: '16px', background: '#0f172a', borderRadius: '6px', overflow: 'hidden', border: '1px solid #1e293b' }}>
                      <div style={{ padding: '8px 12px', background: 'rgba(255,255,255,0.05)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <strong style={{ fontSize: '13px', color: '#10b981' }}>{task.function_name}.rs</strong>
                      </div>
                      <div style={{ padding: '0' }}>
                        <pre style={{ margin: '0', padding: '12px', background: '#020617', fontSize: '12px', color: '#e2e8f0', overflowX: 'auto' }}>
                          {task.translated_artifact}
                        </pre>
                      </div>
                    </div>
                  ))
                )}
              </>
            )}

            {activeTab === 'obligations' && (
              <>
                {closedObligations.length === 0 ? (
                  <div className="phase2-message">No closed obligations recorded.</div>
                ) : (
                  closedObligations.map((item: any, i: number) => (
                    <div key={i} style={{ marginBottom: '16px', background: '#0f172a', borderRadius: '6px', overflow: 'hidden', border: '1px solid #1e293b' }}>
                      <div style={{ padding: '8px 12px', background: 'rgba(255,255,255,0.05)' }}>
                        <strong style={{ fontSize: '13px', color: '#e2e8f0' }}>Target: {item.target_name}</strong>
                      </div>
                      <div style={{ padding: '12px', fontSize: '12px', color: '#cbd5e1' }}>
                        <div style={{ marginBottom: '4px' }}><span style={{ color: '#94a3b8' }}>Task:</span> {item.task_id}</div>
                        <div style={{ marginBottom: '4px' }}><span style={{ color: '#94a3b8' }}>Action:</span> <span style={{ color: '#fbbf24' }}>{item.action}</span></div>
                        <div style={{ marginBottom: '4px' }}><span style={{ color: '#94a3b8' }}>Reason:</span> {item.reason}</div>
                      </div>
                    </div>
                  ))
                )}
              </>
            )}
          </div>
        </div>
      </Split>
    </div>
  );
}
