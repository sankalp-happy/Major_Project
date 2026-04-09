import { useEffect, useRef } from 'react';
import CytoscapeComponent from 'react-cytoscapejs';
import cytoscape from 'cytoscape';

interface GraphViewerProps {
  selectedSymbol: string | null;
  sdgData: any;
  onSelectSymbol?: (symbol: string | null) => void;
}

export function GraphViewer({ selectedSymbol, sdgData, onSelectSymbol }: GraphViewerProps) {
  const cyRef = useRef<cytoscape.Core | null>(null);

  useEffect(() => {
    if (!cyRef.current || !sdgData) return;

    const cy = cyRef.current;
    
    cy.elements().removeClass('highlighted');
    cy.elements().removeClass('faded');
    
    if (selectedSymbol) {
      const targetNode = cy.getElementById(selectedSymbol);
      if (targetNode.length > 0) {
        targetNode.addClass('highlighted');
        const connected = targetNode.neighborhood();
        connected.addClass('highlighted');
        cy.elements().difference(targetNode.union(connected)).addClass('faded');
        
        cy.center(targetNode);
        cy.zoom({ level: 1.2, position: targetNode.position() });
      }
    } else {
      cy.fit();
    }
  }, [selectedSymbol, sdgData]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    const handleNodeTap = (evt: cytoscape.EventObject) => {
      if (onSelectSymbol) {
        onSelectSymbol(evt.target.id());
      }
    };

    const handleBgTap = (evt: cytoscape.EventObject) => {
      if (evt.target === cy && onSelectSymbol) {
        onSelectSymbol(null);
      }
    };

    cy.on('tap', 'node', handleNodeTap);
    cy.on('tap', handleBgTap);

    return () => {
      cy.removeListener('tap', 'node', handleNodeTap);
      cy.removeListener('tap', handleBgTap);
    };
  }, [onSelectSymbol]);

  if (!sdgData || !sdgData.nodes || !sdgData.edges) {
    return <div className="graph-panel"><div className="panel-header">Dependency Topology</div><div className="graph-container"></div></div>;
  }

  const elements: any[] = [];
  
  sdgData.nodes.forEach((node: any) => {
    const type = node.node_type || 'Unknown';
    elements.push({
      data: {
        id: node.id,
        label: node.name || node.id.split(':').pop() || node.id,
        type: type,
      },
      classes: type.toLowerCase(),
    });
  });

  sdgData.edges.forEach((edge: any, index: number) => {
    const type = edge.edge_type || 'Unknown';
    elements.push({
      data: {
        id: `e${index}`,
        source: edge.source,
        target: edge.target,
        label: type,
      },
      classes: type.toLowerCase(),
    });
  });

  const stylesheet = [
    {
      selector: 'node',
      style: {
        'background-color': '#222',
        'border-width': 1,
        'border-color': '#00f0ff',
        'label': 'data(label)',
        'color': '#00f0ff',
        'text-valign': 'bottom',
        'text-halign': 'center',
        'text-margin-y': 5,
        'font-size': '10px',
        'font-family': "'JetBrains Mono', 'Fira Code', monospace",
        'text-outline-width': 2,
        'text-outline-color': '#000',
        'width': '20px',
        'height': '20px',
        'shape': 'diamond',
      }
    },
    {
      selector: 'node.function',
      style: {
        'background-color': '#ff003c',
        'border-color': '#ff003c',
        'color': '#ff003c',
        'shape': 'ellipse',
      }
    },
    {
      selector: 'node.variable',
      style: {
        'background-color': '#fcee0a',
        'border-color': '#fcee0a',
        'color': '#fcee0a',
        'shape': 'rectangle',
        'width': '24px',
      }
    },
    {
      selector: 'node.file',
      style: {
        'background-color': '#00ff41',
        'border-color': '#00ff41',
        'color': '#00ff41',
        'shape': 'hexagon',
        'width': '30px',
        'height': '30px',
      }
    },
    {
      selector: 'edge',
      style: {
        'width': 1,
        'line-color': '#333',
        'target-arrow-color': '#333',
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        'label': 'data(label)',
        'font-size': '8px',
        'color': '#555',
        'text-rotation': 'autorotate',
        'text-margin-y': -8,
        'text-background-opacity': 1,
        'text-background-color': '#000',
        'text-background-padding': 2,
      }
    },
    {
      selector: 'edge.calls',
      style: {
        'line-color': '#ff003c',
        'target-arrow-color': '#ff003c',
        'width': 2,
        'color': '#ff003c',
      }
    },
    {
      selector: 'edge.reads',
      style: {
        'line-style': 'dashed',
        'line-color': '#00f0ff',
        'target-arrow-color': '#00f0ff',
        'color': '#00f0ff',
      }
    },
    {
      selector: 'edge.writes',
      style: {
        'line-style': 'dashed',
        'line-color': '#fcee0a',
        'target-arrow-color': '#fcee0a',
        'color': '#fcee0a',
      }
    },
    {
      selector: 'edge.includes',
      style: {
        'line-color': '#00ff41',
        'target-arrow-color': '#00ff41',
        'color': '#00ff41',
      }
    },
    {
      selector: '.highlighted',
      style: {
        'border-width': 4,
        'border-color': '#fff',
        'width': '40px',
        'height': '40px',
        'z-index': 9999,
        'color': '#fff',
        'text-outline-width': 4,
        'opacity': 1,
      }
    },
    {
      selector: 'edge.highlighted',
      style: {
        'width': 4,
        'opacity': 1,
      }
    },
    {
      selector: '.faded',
      style: {
        'opacity': 0.1,
      }
    }
  ];

  return (
    <div className="graph-panel">
      <div className="panel-header">Dependency Topology</div>
      <div className="graph-overlay">
        <button className="cyber-btn" onClick={() => cyRef.current?.fit()}>Recenter Map</button>
      </div>
      
      <div className="graph-container">
        <CytoscapeComponent
          elements={elements}
          style={{ width: '100%', height: '100%', backgroundColor: '#050505' }}
          stylesheet={stylesheet as cytoscape.StylesheetStyle[]}
          layout={{
            name: 'cose',
            idealEdgeLength: 100,
            nodeOverlap: 20,
            refresh: 20,
            fit: true,
            padding: 30,
            randomize: false,
            componentSpacing: 100,
            nodeRepulsion: 400000,
            edgeElasticity: 100,
            nestingFactor: 5,
          }}
          cy={(cy: cytoscape.Core) => { cyRef.current = cy; }}
        />
      </div>
    </div>
  );
}