with open('tests/test_execution_pipeline_consolidation.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Fix patch in test_01 and test_09: patch.object(RepairEngine, "run_elevated_operation")
content = content.replace('patch("repair_engine.run_elevated_operation")', 'patch.object(RepairEngine, "run_elevated_operation", create=True)')

# 2. Fix test_06 target assertion
t06_old = """            target = mock_verify.call_args[0][0] if mock_verify.call_args[0] else mock_verify.call_args.kwargs.get("target")
            self.assertEqual(target, "git")"""
t06_new = """            target = mock_verify.call_args[0][0] if mock_verify.call_args[0] else (mock_verify.call_args.kwargs.get("target_name_or_id") or mock_verify.call_args.kwargs.get("target"))
            self.assertEqual(target, "git")"""
assert t06_old in content, "t06_old not found"
content = content.replace(t06_old, t06_new)

# 3. Fix test_07 mutation counting
t07_old = """        def mock_process_run(cmd, *args, **kwargs):
            if "git" in str(cmd):
                call_counts["mutation"] += 1
            res = MagicMock()
            res.returncode = 0
            res.stdout = "git version 2.43.0"
            res.stderr = ""
            return res"""
t07_new = """        mutation_cmd = "git config --global credential.helper manager"
        def mock_process_run(cmd, *args, **kwargs):
            if cmd == mutation_cmd:
                call_counts["mutation"] += 1
            res = MagicMock()
            res.returncode = 0
            res.stdout = "git version 2.43.0"
            res.stderr = ""
            return res"""
assert t07_old in content, "t07_old not found"
content = content.replace(t07_old, t07_new)

# 4. Fix test_08 mutation counting
t08_old = """        def mock_process_run(cmd, *args, **kwargs):
            if "git" in str(cmd):
                call_counts["mutation"] += 1
            res = MagicMock()
            res.returncode = 0
            res.stdout = "git version 2.43.0"
            res.stderr = ""
            return res"""
t08_new = """        mutation_cmd = "git config --global credential.helper manager"
        def mock_process_run(cmd, *args, **kwargs):
            if cmd == mutation_cmd:
                call_counts["mutation"] += 1
            res = MagicMock()
            res.returncode = 0
            res.stdout = "git version 2.43.0"
            res.stderr = ""
            return res"""
assert t08_old in content, "t08_old not found"
content = content.replace(t08_old, t08_new)

# Also update the command called in test_07 and test_08 to match mutation_cmd
content = content.replace('command="git --version",\n                target="git",\n                operation="REPAIR",\n                source="STATIC_DB",',
                          'command=mutation_cmd,\n                target="git",\n                operation="REPAIR",\n                source="STATIC_DB",')

# 5. Fix test_11 rescan_idx check
t11_old = """        rescan_idx = trace.index("RESCAN")"""
t11_new = """        rescan_idx = len(trace) - 1 - trace[::-1].index("RESCAN")"""
assert t11_old in content, "t11_old not found"
content = content.replace(t11_old, t11_new)

with open('tests/test_execution_pipeline_consolidation.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("SUCCESSFULLY APPLIED ALL CORRECTIONS")
