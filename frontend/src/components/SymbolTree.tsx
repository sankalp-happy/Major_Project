interface SymbolTreeProps {
  sdgData: any;
  selectedSymbol: string | null;
  onSelectSymbol: (symbol: string) => void;
}

export function SymbolTree({ sdgData, selectedSymbol, onSelectSymbol }: SymbolTreeProps) {
  if (!sdgData || !sdgData.nodes) {
    return <div className="tree-container"><div className="comment">// Loading data...</div></div>;
  }

  // Group nodes by their node_type
  const groups: Record<string, any[]> = {};
  
  sdgData.nodes.forEach((node: any) => {
    const type = node.node_type || 'Unknown';
    if (!groups[type]) groups[type] = [];
    groups[type].push(node);
  });

  return (
    <div className="tree-container">
      {Object.entries(groups).map(([type, nodes]) => (
        <div key={type} className="file-group">
          <div className="file-name">{type.charAt(0).toUpperCase() + type.slice(1)}s</div>
          {nodes.map(node => (
            <div 
              key={node.id} 
              className={`symbol-item ${selectedSymbol === node.id ? 'active' : ''}`}
              onClick={() => onSelectSymbol(node.id)}
            >
              <span>{node.name || node.id.split(':').pop() || node.id}</span>
              <span className="sym-type">{type.substring(0, 3)}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}