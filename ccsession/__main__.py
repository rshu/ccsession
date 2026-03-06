"""Allow running ccsession as a module: python -m ccsession"""
import sys
from ccsession.cli import main

sys.exit(main())
