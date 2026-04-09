import { useEffect, useState } from 'react';

interface CodeViewerProps {
  selectedSymbol: string | null;
  sdgData: any;
}

export function CodeViewer({ selectedSymbol, sdgData }: CodeViewerProps) {
  const [codeContent, setCodeContent] = useState<string>('// Please select a node to view metadata');

  useEffect(() => {
    if (!selectedSymbol || !sdgData) return;

    const node = sdgData.nodes.find((n: any) => n.id === selectedSymbol);
    if (node) {
      const type = node.node_type || 'Unknown';
      const metaStr = JSON.stringify(node, null, 2);
      setCodeContent(`/*\n * IDENTIFIER: ${node.id}\n * TYPE: ${type}\n */\n\nconst metadata = ${metaStr};`);
    } else {
      setCodeContent(`// Error: Node ${selectedSymbol} not found`);
    }
  }, [selectedSymbol, sdgData]);

  // Very basic cyber highlighting
  const highlighted = codeContent.split('\n').map((line, idx) => {
    if (line.trim().startsWith('//') || line.trim().startsWith('/*') || line.trim().startsWith('*')) {
      return <div key={idx} className="comment">{line}</div>;
    }
    // simple string highlighting
    const parts = line.split(/("[^"]*")/g);
    return (
      <div key={idx}>
        {parts.map((p, i) => 
          p.startsWith('"') ? <span key={i} className="string">{p}</span> : <span key={i}>{p}</span>
        )}
      </div>
    );
  });

  return (
    <div className="code-panel">
      <div className="panel-header">Source Metadata Inspector</div>
      <div className="code-content">
        <pre><code>{highlighted}</code></pre>
      </div>
    </div>
  );
}