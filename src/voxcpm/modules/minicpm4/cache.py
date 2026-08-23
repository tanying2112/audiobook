from typing import List, Tuple

import torch


class StaticKVCache:
    def __init__(
        self,
        num_layers: int,
        num_kv_heads: int,
        dim_kv_head: int,
        batch_size: int,
        device: torch.device,
        dtype: torch.dtype,
        max_length: int = 8192,
    ):
        self.max_length = max_length
        self.num_layers = num_layers

        self.kv_cache = torch.zeros(
            2,
            num_layers,
            batch_size,
            num_kv_heads,
            max_length,
            dim_kv_head,
            device=device,
            dtype=dtype,
        )
        self.current_length = 0

    def get_layer_cache(self, layer_idx: int) -> Tuple[torch.Tensor, torch.Tensor]:
        return self.kv_cache[0, layer_idx], self.kv_cache[1, layer_idx]

    def step(self) -> int:
        if self.current_length >= self.max_length:
            raise ValueError("KV cache is full")

        ret = self.current_length
        self.current_length += 1
        return ret

    def fill_caches(self, kv_caches: List[Tuple[torch.Tensor, torch.Tensor]]):
        # Handle GQA: incoming KV tensors may have been expanded from num_kv_heads to num_heads
        # Cache stores only num_kv_heads; we need to select the first group of heads
        self.current_length = kv_caches[0][0].size(2)
        self.kv_cache.zero_()
        for i in range(self.num_layers):
            key_tensor = kv_caches[i][0]
            value_tensor = kv_caches[i][1]
            # Handle GQA expansion: if tensor has num_heads instead of num_kv_heads,
            # select every (num_heads // num_kv_heads) heads to get back num_kv_heads
            if key_tensor.size(1) > self.kv_cache.size(3):
                # Expanded from num_kv_heads to num_heads; take every group to downsample
                heads_per_group = key_tensor.size(1) // self.kv_cache.size(3)
                key_tensor = key_tensor[:, ::heads_per_group, :, :]
                value_tensor = value_tensor[:, ::heads_per_group, :, :]
            self.kv_cache[0, i, :, :, : self.current_length, :] = key_tensor
            self.kv_cache[1, i, :, :, : self.current_length, :] = value_tensor
