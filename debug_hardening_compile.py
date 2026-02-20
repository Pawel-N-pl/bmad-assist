
import sys
from pathlib import Path

# Add src to python path
sys.path.append("/Users/regisgesnot/DevProjects/bmad-assist-devRGT/src")

from bmad_assist.compiler.workflows.hardening import HardeningCompiler
from bmad_assist.compiler.types import CompilerContext
from bmad_assist.core.config import load_config_with_project
from bmad_assist.core.paths import init_paths, get_paths

project_path = Path("/Users/regisgesnot/DevProjects/bmad-assist-devRGT")
config = load_config_with_project(project_path=project_path)

# Init paths
paths_config = {
    "output_folder": config.paths.output_folder,
    "planning_artifacts": config.paths.planning_artifacts,
    "implementation_artifacts": config.paths.implementation_artifacts,
    "project_knowledge": config.paths.project_knowledge,
}
init_paths(project_path, paths_config)

compiler = HardeningCompiler()
context = CompilerContext(
    project_root=project_path,
    output_folder=get_paths().output_folder,
    project_knowledge=get_paths().project_knowledge,
    cwd=Path.cwd(),
    resolved_variables={"epic_num": 4},
    workflow_ir=None # this will fail, need to load it
)

# Load workflow IR
from bmad_assist.compiler.workflow_discovery import discover_workflow_dir
from bmad_assist.compiler.parsing import parse_workflow_yaml
workflow_dir = discover_workflow_dir("hardening", project_path)
workflow_ir = parse_workflow_yaml(workflow_dir / "workflow.yaml")
context.workflow_ir = workflow_ir

try:
    compiled = compiler.compile(context)
    print("--- MISSION ---")
    print(compiled.mission)
    print("\n--- CONTEXT (Start) ---")
    print(compiled.context[:500])
    print("\n--- INSTRUCTIONS (Start) ---")
    print(compiled.instructions[:500])
except Exception as e:
    print(f"Compilation failed: {e}")
    import traceback
    traceback.print_exc()
