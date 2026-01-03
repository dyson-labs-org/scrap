# SCAP/SISL Presentation Build System
#
# Builds audience-specific presentations from modular slide fragments.
#
# Usage:
#   make all          - Build all presentations
#   make nasa         - Build NASA presentation only
#   make darpa        - Build DARPA presentation only
#   make commercial   - Build Commercial presentation only
#   make clean        - Remove generated files
#
# Output files are created in the parent directory.

OUTDIR := ..

# Common slide fragments (in order)
COMMON_SLIDES := \
	common/01_title.html \
	common/02_problem.html \
	common/03_vision.html \
	common/04_sisl.html \
	common/05_scap.html \
	common/05b_delegation.html \
	common/05c_payment.html \
	common/06_architecture.html \
	common/07_security.html \
	common/07b_risks.html \
	common/08_phase1_demo.html \
	common/09_roadmap.html \
	common/10_implementation.html

# Audience-specific slides
NASA_SLIDES := \
	nasa/ccsds_alignment.html \
	nasa/trl_progression.html \
	nasa/cta.html

DARPA_SLIDES := \
	darpa/contested_env.html \
	darpa/cta.html

COMMERCIAL_SLIDES := \
	commercial/market.html \
	commercial/cta.html

# Output files
NASA_OUTPUT := $(OUTDIR)/SLIDESHOW_NASA.html
DARPA_OUTPUT := $(OUTDIR)/SLIDESHOW_DARPA.html
COMMERCIAL_OUTPUT := $(OUTDIR)/SLIDESHOW_COMMERCIAL.html

.PHONY: all clean nasa darpa commercial

all: nasa darpa commercial
	@echo "Built all presentations:"
	@echo "  $(NASA_OUTPUT)"
	@echo "  $(DARPA_OUTPUT)"
	@echo "  $(COMMERCIAL_OUTPUT)"

nasa: $(NASA_OUTPUT)

darpa: $(DARPA_OUTPUT)

commercial: $(COMMERCIAL_OUTPUT)

$(NASA_OUTPUT): common/_head.html $(COMMON_SLIDES) $(NASA_SLIDES) common/_tail.html
	@echo "Building NASA presentation..."
	@sed 's/<!-- TITLE -->/SCAP\/SISL - NASA/' common/_head.html > $@
	@cat $(COMMON_SLIDES) >> $@
	@cat $(NASA_SLIDES) >> $@
	@cat common/_tail.html >> $@
	@echo "  Created $@"

$(DARPA_OUTPUT): common/_head.html $(COMMON_SLIDES) $(DARPA_SLIDES) common/_tail.html
	@echo "Building DARPA presentation..."
	@sed 's/<!-- TITLE -->/SCAP\/SISL - DARPA/' common/_head.html > $@
	@cat $(COMMON_SLIDES) >> $@
	@cat $(DARPA_SLIDES) >> $@
	@cat common/_tail.html >> $@
	@echo "  Created $@"

$(COMMERCIAL_OUTPUT): common/_head.html $(COMMON_SLIDES) $(COMMERCIAL_SLIDES) common/_tail.html
	@echo "Building Commercial presentation..."
	@sed 's/<!-- TITLE -->/SCAP\/SISL - Commercial/' common/_head.html > $@
	@cat $(COMMON_SLIDES) >> $@
	@cat $(COMMERCIAL_SLIDES) >> $@
	@cat common/_tail.html >> $@
	@echo "  Created $@"

clean:
	rm -f $(NASA_OUTPUT) $(DARPA_OUTPUT) $(COMMERCIAL_OUTPUT)
	@echo "Cleaned generated presentations"

# Watch for changes and rebuild (requires inotifywait)
watch:
	@echo "Watching for changes... (Ctrl+C to stop)"
	@while true; do \
		inotifywait -q -e modify -r common nasa darpa commercial; \
		$(MAKE) all; \
	done
