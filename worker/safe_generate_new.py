def make_safe_generate(orig_generate):
    """Factory function that returns a safe_generate with orig_generate captured via closure.

    Avoids binding orig_generate as an attribute on the model instance.
    Uses closure binding: _orig = orig_generate captured in the factory scope.
    """
    def safe_generate(*g_args, **g_kwargs):
        # 💡 核心修复：g_args 是 tuple，需先转 list 才能修改
        g_args = list(g_args)

        # 1. 从 kwargs 中提取并移除 speaker，防止传给底层报错
        g_speaker = g_kwargs.pop('speaker', None)

        # 如果 kwargs 没有 speaker，检查位置参数 args[1]
        if g_speaker is None and len(g_args) > 1:
            g_speaker = g_args[1]
            g_args[1] = None

        # 字符串 speaker：转为 Voice Design 提示词注入文本
        if isinstance(g_speaker, str):
            print(f"[RUNTIME] Mapping speaker '{g_speaker}' to VoxCPM2 voice design prompt...", flush=True)
            desc = "(A young woman, gentle and sweet clear voice)" if "female" in g_speaker else "(A young man, warm and professional clear voice)"
            if len(g_args) > 0 and isinstance(g_args[0], str) and not g_args[0].startswith("("):
                g_args[0] = desc + g_args[0]
            elif 'text' in g_kwargs:
                if isinstance(g_kwargs['text'], str) and not g_kwargs['text'].startswith("("):
                    g_kwargs['text'] = desc + g_kwargs['text']

        # 无论什么类型，speaker 都从 kwargs 移除，防止传给底层报错
        # 如果是整数 speaker，作为第二个位置参数传给原生 generate
        if g_speaker is not None and not isinstance(g_speaker, str) and len(g_args) > 1:
            g_args[1] = g_speaker

        # 🛡️ 闭包调用：直接调用 _orig，绝不使用 self. 前缀
        return orig_generate(*g_args, **g_kwargs)

    return safe_generate