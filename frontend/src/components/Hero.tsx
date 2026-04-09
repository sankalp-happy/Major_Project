import React from 'react';

interface HeroProps {
  onLocalScanStart: () => void;
}

export function Hero({ onLocalScanStart }: HeroProps) {
  return (
    <div className="hero-container">
      <div className="hero-section hero-intro">
        <h1 className="hero-title">Cartographer</h1>
        <p className="hero-description">
          A comprehensive System Dependence Graph visualization and analysis tool designed for tracking complex code relationships within massive software repositories. This research project presents a novel methodology to understand operational topography in software engineering.
        </p>
      </div>

      <div className="hero-section hero-how-it-works">
        <h2 className="section-title">Methodology</h2>
        <div className="methodology-grid">
          
          <div className="methodology-card">
            <div className="methodology-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path><polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline><line x1="12" y1="22.08" x2="12" y2="12"></line>
              </svg>
            </div>
            <h3>Symbol Extraction</h3>
            <p>Identifies files, functions, and variables directly from the software codebase structural trees.</p>
          </div>

          <div className="methodology-card">
            <div className="methodology-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="18" cy="5" r="3"></circle><circle cx="6" cy="12" r="3"></circle><circle cx="18" cy="19" r="3"></circle><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"></line><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"></line>
              </svg>
            </div>
            <h3>Dependency Resolution</h3>
            <p>Traces functional read, write, call, and include edges to formulate a detailed reliance map.</p>
          </div>

          <div className="methodology-card">
            <div className="methodology-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line><path d="M11 8v6"></path><path d="M8 11h6"></path>
              </svg>
            </div>
            <h3>Interactive Visualization</h3>
            <p>Generates an traversable dependency graph that facilitates rigorous root cause analysis and software reviews.</p>
          </div>

        </div>
      </div>

      <div className="hero-section hero-cta">
        <h2 className="section-title">Target Analysis Space</h2>
        <div className="button-group">
          <button className="cyber-btn primary-btn active" onClick={onLocalScanStart}>
            Scan Local Repository
          </button>
          <button className="cyber-btn secondary-btn" disabled style={{opacity: 0.5, cursor: 'not-allowed'}}>
            Clone from GitHub (Disabled)
          </button>
        </div>
      </div>
    </div>
  );
}
