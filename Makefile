################################################################################
#
#   Makefile for ARC
#
################################################################################

.PHONY : clean gcn gcn-cpu test test-unittests

test test-unittests:
	pytest arc/ --cov -ra -vv

test-functional:
	pytest functional/ -ra -vv

install-all:
	bash devtools/install_all.sh

install-autotst:
	bash devtools/install_autotst.sh

install-gcn:
	bash devtools/install_gcn.sh

install-gcn-cpu:
	bash devtools/install_gcn_cpu.sh

install-kinbot:
	bash devtools/install_kinbot.sh

install-sella:
	bash devtools/install_sella.sh

install-xtb:
	bash devtools/install_xtb.sh

lite:
	bash devtools/lite.sh

clean:
	find -type d -name __pycache__ -exec rm -rf {} +
	rm -rf testing
	rm -rf arc/testing/gcn_tst
	rm -f .coverage
