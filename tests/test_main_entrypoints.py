"""测试入口文件使用 AppContainer 结构。"""
import ast
import unittest
from pathlib import Path


MAIN_SCRIPT = Path(__file__).parents[1] / "视频下载工具v2.0.0-GUI.py"


class MainEntrypointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(MAIN_SCRIPT.read_text(encoding="utf-8"))

    def test_entry_point_uses_app_container(self):
        """验证入口文件使用 AppContainer 进行依赖注入。"""
        imports = [node for node in ast.walk(self.tree) if isinstance(node, ast.ImportFrom)]
        import_modules = []
        for node in imports:
            if node.module:
                import_modules.append(node.module)
        self.assertIn("video_downloader.container", import_modules,
                      "入口文件应导入 AppContainer")

    def test_main_function_is_simple(self):
        """验证 main() 函数结构简洁（委托给 container）。"""
        main_funcs = [node for node in self.tree.body
                      if isinstance(node, ast.FunctionDef) and node.name == "main"]
        self.assertEqual(len(main_funcs), 1, "应有一个 main() 函数")
        body = main_funcs[0].body
        # main() 应该调用 app.main()
        calls = [ast.unparse(node.func) for node in ast.walk(main_funcs[0])
                 if isinstance(node, ast.Call)]
        self.assertIn("app.main", calls, "main() 应委托给 app.main()")

    def test_container_is_constructed(self):
        """验证 AppContainer 在模块级别被构造。"""
        calls = [ast.unparse(node.func) for node in ast.walk(self.tree)
                 if isinstance(node, ast.Call)]
        self.assertIn("AppContainer", calls, "应构造 AppContainer")
        self.assertIn("container.wire", calls, "应调用 container.wire()")

    def test_entry_point_imports_core_constants(self):
        """验证入口文件从 core.constants 导入（而非旧路径）。"""
        imports = [node for node in ast.walk(self.tree) if isinstance(node, ast.ImportFrom)]
        found = False
        for node in imports:
            if node.module and "core.constants" in node.module:
                found = True
                break
        self.assertTrue(found, "应从 video_downloader.core.constants 导入")

    def test_sys_frozen_path_logic_present(self):
        """验证 PyInstaller 兼容路径逻辑存在。"""
        source = MAIN_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("getattr(sys, 'frozen'", source,
                      "应包含 PyInstaller frozen 检测")
        self.assertIn("sys.executable", source,
                      "应使用 sys.executable 获取路径")


if __name__ == "__main__":
    unittest.main()
