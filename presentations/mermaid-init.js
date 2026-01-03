// Initialize Mermaid for reveal.js/reveal-md
(function() {
  function initMermaid() {
    if (typeof mermaid === 'undefined') {
      console.log('Mermaid not loaded yet, retrying...');
      setTimeout(initMermaid, 100);
      return;
    }

    mermaid.initialize({
      startOnLoad: false,
      theme: 'dark',
      themeVariables: {
        primaryColor: '#58a6ff',
        primaryTextColor: '#e6edf3',
        primaryBorderColor: '#30363d',
        lineColor: '#8b949e',
        secondaryColor: '#161b22',
        tertiaryColor: '#0d1117',
        background: 'transparent',
        mainBkg: '#161b22',
        nodeBorder: '#30363d',
        clusterBkg: '#161b22',
        clusterBorder: '#30363d',
        titleColor: '#58a6ff',
        edgeLabelBackground: '#161b22'
      }
    });

    // Find mermaid code blocks - reveal-md puts them in <code class="language-mermaid">
    var diagrams = document.querySelectorAll('code.language-mermaid, code.mermaid, pre.mermaid');

    diagrams.forEach(function(el, index) {
      var code = el.textContent || el.innerText;
      var container = el.tagName === 'CODE' ? el.parentElement : el;
      var id = 'mermaid-diagram-' + index;

      try {
        mermaid.render(id, code).then(function(result) {
          container.innerHTML = result.svg;
          container.classList.add('mermaid-rendered');
        }).catch(function(err) {
          console.error('Mermaid render error:', err);
        });
      } catch (err) {
        console.error('Mermaid error:', err);
      }
    });
  }

  // Wait for DOM and scripts to load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMermaid);
  } else {
    // DOM already loaded, wait a bit for mermaid script
    setTimeout(initMermaid, 100);
  }
})();
