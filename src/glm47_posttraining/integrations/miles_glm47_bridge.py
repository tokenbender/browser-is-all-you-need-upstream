from __future__ import annotations

import os
from typing import Any


_REGISTERED = False
_MBRIDGE_PATCHED = False
_SHARED_OUTER_CKPT_PATCHED = False
_LORA_SYNC_PATCHED = False
_SGLANG_MEM_POOL_PATCHED = False
_ROUTER_CB_PATCHED = False
_WARM_START_OPT_PATCHED = False
_LORA_TMS_PATCHED = False
_LORA_UPDATE_TMS_PATCHED = False
_ROLLOUT_DP_SHARD_PATCHED = False
_CORRECT_SAMPLE_LOG_PATCHED = False


def register_glm47_bridge() -> None:













    _when_imported("mbridge.core.bridge", lambda module: _patch_mbridge_glm47_lite())
    _when_imported("miles_plugins.mbridge", lambda module: _patch_mbridge_glm47_lite())
    _when_imported(
        "megatron.bridge.peft.utils",
        lambda module: _patch_shared_outer_expert_adapter_replication(),
    )
    _patch_sglang_lora_sync_skip_mtp()
    _patch_sglang_lora_mem_pool_ordering()
    _patch_router_circuit_breaker()
    _patch_warm_start_optimizer_reload()
    _patch_colocate_lora_tms_regions()
    _patch_colocate_lora_update_tms_scope()
    _patch_rollout_data_dp_sharding()
    _patch_correct_sample_logging()
    _when_imported("megatron.bridge", lambda module: _register_glm47_bridge_class())


def _register_glm47_bridge_class() -> None:
    global _REGISTERED
    if _REGISTERED:
        return

    try:
        import megatron.bridge.models.glm.glm47_flash_bridge
    except (ImportError, ModuleNotFoundError):
        pass
    else:
        _REGISTERED = True
        return

    from functools import partial

    from megatron.bridge.models.conversion.mapping_registry import MegatronMappingRegistry
    from megatron.bridge.models.conversion.model_bridge import MegatronModelBridge
    from megatron.bridge.models.gpt_provider import GPTModelProvider
    from megatron.bridge.models.hf_pretrained.causal_lm import PreTrainedCausalLM
    from megatron.bridge.models.mla_provider import MLAModelProvider
    from megatron.core.models.gpt.gpt_layer_specs import get_gpt_decoder_block_spec
    from megatron.core.models.gpt.gpt_model import GPTModel

    try:
        import transformer_engine

        have_te = True
    except (ImportError, ModuleNotFoundError):
        have_te = False

    @MegatronModelBridge.register_bridge(
        source="Glm4MoeLiteForCausalLM",
        target=GPTModel,
        provider=MLAModelProvider,
        model_type="glm4_moe_lite",
    )
    class GLM47LiteBridge(MegatronModelBridge):


        def provider_bridge(self, hf_pretrained: PreTrainedCausalLM) -> GPTModelProvider:
            provider = super().provider_bridge(hf_pretrained)
            hf_config = hf_pretrained.config




            provider.transformer_layer_spec = partial(get_gpt_decoder_block_spec, use_transformer_engine=have_te)

            provider.normalization = "RMSNorm"
            provider.gated_linear_unit = True
            provider.add_bias_linear = False
            provider.share_embeddings_and_output_weights = False
            provider.qk_layernorm = True
            provider.multi_latent_attention = True
            provider.mtp_num_layers = getattr(hf_config, "num_nextn_predict_layers", None)
            provider.mtp_loss_scaling_factor = 0.3

            provider.moe_grouped_gemm = True
            provider.moe_router_pre_softmax = True
            provider.moe_token_dispatcher_type = "alltoall"
            provider.moe_router_load_balancing_type = "seq_aux_loss"
            provider.moe_shared_expert_overlap = True
            provider.moe_router_score_function = "sigmoid"
            provider.moe_router_enable_expert_bias = True
            provider.moe_router_dtype = "fp32"
            provider.moe_permute_fusion = True
            provider.moe_router_bias_update_rate = 0
            provider.moe_aux_loss_coeff = 0.0

            provider.hidden_dropout = 0.0
            provider.attention_softmax_in_fp32 = True
            provider.make_vocab_size_divisible_by = 64
            provider.moe_layer_freq = [0] * hf_config.first_k_dense_replace + [1] * (
                hf_config.num_hidden_layers - hf_config.first_k_dense_replace
            )
            provider.moe_shared_expert_intermediate_size = (
                hf_config.moe_intermediate_size * getattr(hf_config, "n_shared_experts", 1)
            )
            provider.rotary_base = getattr(hf_config, "rope_theta", 1000000)
            provider.rotary_scaling_factor = 1.0
            provider.mscale = 1.0
            provider.mscale_all_dim = 1.0

            return provider

        def mapping_registry(self) -> MegatronMappingRegistry:
            mappings = _glm47_base_mappings()
            mappings.extend(_glm47_mtp_mappings(self.hf_config))
            return MegatronMappingRegistry(*mappings)

    _REGISTERED = True


def _patch_mbridge_glm47_lite() -> None:


    global _MBRIDGE_PATCHED
    if _MBRIDGE_PATCHED:
        return

    try:
        import miles_plugins.mbridge
        from mbridge.core.bridge import _MODEL_REGISTRY
    except (ImportError, ModuleNotFoundError):
        return

    glm_bridge = _MODEL_REGISTRY.get("glm4_moe_lite")
    if glm_bridge is None:
        return

    attention_mapping = dict(getattr(glm_bridge, "_ATTENTION_MAPPING", {}))
    attention_mapping.setdefault(
        "self_attention.linear_qkv.layer_norm_weight",
        ["model.layers.{layer_number}.input_layernorm.weight"],
    )
    glm_bridge._ATTENTION_MAPPING = attention_mapping
    _MBRIDGE_PATCHED = True


def _patch_shared_outer_expert_adapter_replication() -> None:











    global _SHARED_OUTER_CKPT_PATCHED
    if _SHARED_OUTER_CKPT_PATCHED:
        return
    if os.environ.get("GLM47_DISABLE_SHARED_LORA_CKPT_PATCH", "").strip().lower() in {"1", "true", "yes", "on"}:
        return

    try:
        from megatron.bridge.peft import utils as peft_utils
    except (ImportError, ModuleNotFoundError):
        return

    adapter_cls = getattr(peft_utils, "SharedOuterGroupedExpertAdapter", None)
    if adapter_cls is None or getattr(adapter_cls, "_glm47_ep_replica_patched", False):
        return

    original_sharded_state_dict = adapter_cls.sharded_state_dict

    def sharded_state_dict(self, prefix="", sharded_offsets=(), metadata=None):
        sharded = original_sharded_state_dict(self, prefix, sharded_offsets, metadata)
        shared_prefix = f"{prefix}linear_in." if getattr(self, "_is_fc1", True) else f"{prefix}linear_out."
        try:
            from megatron.core import parallel_state

            ep_rank = parallel_state.get_expert_model_parallel_rank()
            ep_world = parallel_state.get_expert_model_parallel_world_size()
        except Exception:
            return sharded
        if ep_world <= 1:
            return sharded



        for key, entry in sharded.items():
            if not key.startswith(shared_prefix) or not hasattr(entry, "replica_id"):
                continue
            replica = entry.replica_id
            if isinstance(replica, int):
                entry.replica_id = replica * ep_world + ep_rank
            else:
                replica = tuple(replica)
                if not replica:
                    entry.replica_id = (ep_rank,)
                else:
                    entry.replica_id = (*replica[:-1], replica[-1] * ep_world + ep_rank)
        return sharded

    adapter_cls.sharded_state_dict = sharded_state_dict
    adapter_cls._glm47_ep_replica_patched = True
    _SHARED_OUTER_CKPT_PATCHED = True


def _when_imported(module_name: str, callback) -> None:


    import importlib.abc
    import importlib.util
    import sys

    existing = sys.modules.get(module_name)
    if existing is not None:
        callback(existing)
        return

    class _Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname != module_name:
                return None
            sys.meta_path.remove(self)
            spec = importlib.util.find_spec(fullname)
            if spec is None or spec.loader is None:
                return None
            wrapped = spec.loader

            class _Loader(importlib.abc.Loader):
                def create_module(self, spec_inner):
                    return wrapped.create_module(spec_inner)

                def exec_module(self, module):
                    wrapped.exec_module(module)
                    callback(module)

            spec.loader = _Loader()
            return spec

    sys.meta_path.insert(0, _Finder())


def _patch_sglang_lora_sync_skip_mtp() -> None:









    global _LORA_SYNC_PATCHED
    if _LORA_SYNC_PATCHED:
        return
    if os.environ.get("GLM47_DISABLE_SGLANG_MTP_FILTER", "").strip().lower() in {"1", "true", "yes", "on"}:
        return
    _LORA_SYNC_PATCHED = True
    _when_imported(
        "miles.backends.megatron_utils.update_weight.update_weight_from_tensor",
        _apply_sglang_lora_mtp_filter,
    )


def _patch_warm_start_optimizer_reload() -> None:


    global _WARM_START_OPT_PATCHED
    if _WARM_START_OPT_PATCHED:
        return
    if os.environ.get("GLM47_DISABLE_WARM_START_OPT_RELOAD", "").strip().lower() in {"1", "true", "yes", "on"}:
        return
    _WARM_START_OPT_PATCHED = True
    _when_imported("miles.backends.megatron_utils.lora_utils", _apply_warm_start_optimizer_reload)


def _apply_warm_start_optimizer_reload(module) -> None:
    original_load = getattr(module, "load_lora_adapter", None)
    if original_load is None or getattr(module, "_glm47_opt_reload_patched", False):
        return

    def load_lora_adapter(model, adapter_path, *, optimizer=None, opt_param_scheduler=None):
        resolved = _stage_rank_adapter_dir(module, adapter_path) or adapter_path
        loaded, iteration = original_load(
            model, resolved, optimizer=optimizer, opt_param_scheduler=opt_param_scheduler
        )
        _assert_warm_start_took(model, adapter_path, loaded)
        if loaded and optimizer is not None and hasattr(optimizer, "reload_model_params"):
            optimizer.reload_model_params()
            print(
                "GLM-4.7 warm start: optimizer.reload_model_params() after adapter load "
                "(fp32 masters now match the loaded adapter)",
                flush=True,
            )
        return loaded, iteration

    module.load_lora_adapter = load_lora_adapter
    module._glm47_opt_reload_patched = True


def _stage_rank_adapter_dir(module, adapter_path) -> str | None:













    import re
    import tempfile
    from pathlib import Path

    adapter_dir = Path(adapter_path).resolve()
    if not adapter_dir.is_dir():
        return None
    try:
        dist = module.dist
        global_rank = dist.get_rank() if dist.is_initialized() else 0
        parallel_state = module.get_parallel_state()
        tp_rank = parallel_state.tp.rank
        pp_rank = parallel_state.pp.rank
    except Exception as error:
        print(f"GLM-4.7 warm start shim: rank introspection unavailable ({error})", flush=True)
        return None

    shard = adapter_dir / f"adapter_megatron_rank{global_rank}.pt"
    if not shard.exists():
        shard = None
        pattern = re.compile(r"^adapter_megatron_tp(\d+)_pp(\d+)_ep(\d+)\.pt$")
        for candidate in sorted(adapter_dir.glob("adapter_megatron_tp*_pp*_ep*.pt")):
            match = pattern.fullmatch(candidate.name)
            if match and int(match.group(3)) == global_rank:
                if int(match.group(1)) != tp_rank or int(match.group(2)) != pp_rank:
                    raise RuntimeError(
                        f"{candidate.name} belongs to global rank {global_rank} but this "
                        f"rank is tp{tp_rank}/pp{pp_rank}; adapter layout does not match "
                        "the run's parallel configuration"
                    )
                shard = candidate
                break
    if shard is None:
        return None

    staged = Path(tempfile.mkdtemp(prefix=f"glm47_warmstart_rank{global_rank}_"))
    for item in adapter_dir.iterdir():
        if item.name.startswith("adapter_megatron_"):
            continue
        (staged / item.name).symlink_to(item)
    (staged / f"adapter_megatron_rank{global_rank}.pt").symlink_to(shard)
    (staged / f"adapter_megatron_tp{tp_rank}_pp{pp_rank}.pt").symlink_to(shard)
    print(
        f"GLM-4.7 warm start shim: rank {global_rank} (tp{tp_rank}/pp{pp_rank}) resolves "
        f"{shard.name} via {staged}",
        flush=True,
    )
    return str(staged)


def _assert_warm_start_took(model, adapter_path, loaded) -> None:











    if not adapter_path:
        return
    if os.environ.get("GLM47_ALLOW_COLD_LORA_START", "").strip().lower() in {"1", "true", "yes", "on"}:
        return
    if not loaded:
        raise RuntimeError(
            f"warm start requested from {adapter_path} but the loader reported nothing "
            "loaded; refusing to train from a fresh LoRA init "
            "(set GLM47_ALLOW_COLD_LORA_START=1 for a deliberate cold start)"
        )
    chunks = model if isinstance(model, (list, tuple)) else [model]
    in_count = out_count = 0
    in_norm = out_norm = 0.0
    for chunk in chunks:
        for name, param in chunk.named_parameters():
            if "adapter.linear_in" in name:
                in_count += 1
                in_norm += float(param.detach().float().norm())
            elif "adapter.linear_out" in name:
                out_count += 1
                out_norm += float(param.detach().float().norm())
    print(
        "GLM-4.7 warm start receipt: "
        f'{{"adapter_path": "{adapter_path}", "linear_in_tensors": {in_count}, '
        f'"linear_out_tensors": {out_count}, "linear_in_norm_sum": {in_norm:.6f}, '
        f'"linear_out_norm_sum": {out_norm:.6f}}}',
        flush=True,
    )
    if out_count and out_norm == 0.0:
        raise RuntimeError(
            f"warm start from {adapter_path} left every adapter linear_out (LoRA B) "
            "tensor at zero init on this rank: the adapter file was not actually "
            "restored and the policy is the base model. Refusing to train."
        )


def _patch_colocate_lora_tms_regions() -> None:









    global _LORA_TMS_PATCHED
    if _LORA_TMS_PATCHED:
        return
    if os.environ.get("GLM47_DISABLE_LORA_TMS_PATCH", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return
    _LORA_TMS_PATCHED = True
    _when_imported(
        "miles.backends.megatron_utils.bridge_lora_helpers",
        _apply_colocate_lora_tms_region_patch,
    )


def _apply_colocate_lora_tms_region_patch(module) -> None:
    import importlib

    original_patch = getattr(module, "patch_param_grad_buffer_for_colocate_mode_lora", None)
    if original_patch is None or getattr(module, "_glm47_tms_region_patched", False):
        return

    def patch_param_grad_buffer_for_colocate_mode_lora() -> None:
        lora_utils = importlib.import_module("miles.backends.megatron_utils.lora_utils")
        if getattr(lora_utils, "_param_grad_buffer_patched", False):
            return

        param_buffer_module = importlib.import_module(
            "megatron.core.distributed.param_and_grad_buffer"
        )
        buffer_cls = param_buffer_module._ParamAndGradBuffer
        original_init = buffer_cls.__init__
        resident_pools = {}

        def __init__(self, *args, **kwargs):



            kwargs["disable_param_buffers_cpu_backup"] = False
            kwargs["disable_grad_buffers_cpu_backup"] = False

            torch_module = importlib.import_module("torch")
            device = torch_module.cuda.current_device()
            resident_pool = resident_pools.get(device)
            if resident_pool is None:
                resident_pool = torch_module.cuda.MemPool()
                resident_pools[device] = resident_pool

            tms_module = importlib.import_module("torch_memory_saver")
            memory_saver = tms_module.torch_memory_saver
            impl = getattr(memory_saver, "_impl", None)
            cdll = getattr(getattr(impl, "_binary_wrapper", None), "cdll", None)
            was_interesting = bool(cdll and cdll.tms_get_interesting_region())
            if was_interesting:
                cdll.tms_set_interesting_region(False)
            try:
                with torch_module.cuda.use_mem_pool(resident_pool):
                    original_init(self, *args, **kwargs)
            finally:
                if was_interesting:
                    cdll.tms_set_interesting_region(True)

        buffer_cls.__init__ = __init__
        buffer_cls._glm47_resident_lora_pools = resident_pools
        lora_utils._param_grad_buffer_patched = True
        lora_utils.patch_param_grad_buffer_for_colocate_mode_lora = (
            patch_param_grad_buffer_for_colocate_mode_lora
        )
        print(
            "GLM-4.7 colocate: resident LoRA DDP buffers use a persistent non-pauseable pool",
            flush=True,
        )

    module.patch_param_grad_buffer_for_colocate_mode_lora = (
        patch_param_grad_buffer_for_colocate_mode_lora
    )
    module._glm47_tms_region_patched = True


def _patch_colocate_lora_update_tms_scope() -> None:


    global _LORA_UPDATE_TMS_PATCHED
    if _LORA_UPDATE_TMS_PATCHED:
        return
    if os.environ.get("GLM47_DISABLE_UPDATE_TMS_PATCH", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return
    _LORA_UPDATE_TMS_PATCHED = True
    _when_imported(
        "miles.backends.megatron_utils.actor",
        _apply_colocate_lora_update_tms_scope,
    )


def _apply_colocate_lora_update_tms_scope(module) -> None:













    cls = getattr(module, "MegatronTrainRayActor", None)
    if cls is None or getattr(cls, "_glm47_update_tms_scope_patched", False):
        return

    def sleep(self) -> None:
        assert self.args.offload_train

        if module.is_lora_enabled(self.args):
            snapshots = _snapshot_lora_parameters(self.model)
            if not snapshots:
                raise RuntimeError(
                    "LoRA sync snapshot failed: the actor model has no adapter parameters"
                )
            self._glm47_lora_sync_snapshots = snapshots
            snapshot_bytes = sum(tensor.numel() * tensor.element_size() for _, tensor, _ in snapshots)
            print(
                "GLM-4.7 LoRA sync snapshot: "
                f"rank={module.dist.get_rank()} tensors={len(snapshots)} "
                f"gib={snapshot_bytes / (1024**3):.3f}",
                flush=True,
            )

        module.clear_memory(clear_host_memory=True)
        module.print_memory("before offload model")
        module.destroy_process_groups()

        tag = "default" if module.is_lora_enabled(self.args) else None
        module.torch_memory_saver.pause(tag=tag)

        module.print_memory("after offload model")

        if getattr(self, "_is_main_rank", False) and hasattr(self, "_last_rollout_id"):
            module.log_cpu_memory(
                self._last_rollout_id, self.args, "after_offload_train"
            )

    def update_weights(self, info) -> None:
        if self.args.debug_train_only or self.args.debug_rollout_only:
            return

        rollout_engines = info.rollout_engines
        rollout_engine_lock = info.rollout_engine_lock
        has_new_engines = info.has_new_engines
        engine_gpu_counts = info.engine_gpu_counts
        engine_gpu_offsets = info.engine_gpu_offsets
        del info

        context = (
            module.torch_memory_saver.disable()
            if self.args.offload_train
            else module.nullcontext()
        )
        with context:
            staged_param_data = []
            try:
                if self.args.offload_train:
                    module.reload_process_groups()

                if has_new_engines:
                    self.weight_updater.connect_rollout_engines(
                        rollout_engines,
                        rollout_engine_lock,
                        engine_gpu_counts=engine_gpu_counts,
                        engine_gpu_offsets=engine_gpu_offsets,
                    )
                    module.dist.barrier(group=module.get_gloo_group())
                    if module.dist.get_rank() == 0:
                        module.ray.get(
                            self.rollout_manager.clear_updatable_has_new_engines.remote()
                        )

                if self.args.debug_skip_weight_update:
                    if module.dist.get_rank() == 0:
                        module.logger.warning(
                            "Skipping actor-to-rollout weight update because "
                            "--debug-skip-weight-update is set."
                        )
                    return

                if self.args.offload_train and module.is_lora_enabled(self.args):
                    snapshots = getattr(self, "_glm47_lora_sync_snapshots", None)
                    if not snapshots:
                        raise RuntimeError(
                            "LoRA weight sync has no pre-offload adapter snapshot"
                        )
                    staged_bytes = 0
                    for param, cpu_tensor, device in snapshots:
                        staged_param_data.append((param, param.data))
                        param.data = cpu_tensor.to(
                            device=device,
                            non_blocking=False,
                        )
                        staged_bytes += cpu_tensor.numel() * cpu_tensor.element_size()
                    module.torch.cuda.synchronize()
                    print(
                        "GLM-4.7 LoRA sync staging: "
                        f"rank={module.dist.get_rank()} tensors={len(snapshots)} "
                        f"gib={staged_bytes / (1024**3):.3f}",
                        flush=True,
                    )

                module.print_memory("before update_weights")
                self.weight_updater.update_weights()
                module.print_memory("after update_weights")

                if (
                    self.args.ci_test
                    and len(rollout_engines) > 0
                    and not module.is_lora_enabled(self.args)
                ):
                    engine = module.random.choice(rollout_engines)
                    engine_version = module.ray.get(engine.get_weight_version.remote())
                    if str(engine_version) != str(self.weight_updater.weight_version):
                        raise RuntimeError(
                            "Weight version mismatch! "
                            f"Engine: {engine_version}, "
                            f"Updater: {self.weight_updater.weight_version}"
                        )

                if getattr(self.args, "keep_old_actor", False):
                    if self.args.update_weights_interval == 1:
                        module.logger.info(
                            "updating model queue: rollout_actor -> old_actor, "
                            "actor -> rollout_actor"
                        )
                        self.weights_backuper.copy(
                            src_tag="rollout_actor", dst_tag="old_actor"
                        )
                        self.weights_backuper.backup("rollout_actor")
                    else:
                        self.weights_backuper.backup("old_actor")
            finally:
                if staged_param_data:
                    module.torch.cuda.synchronize()
                    for param, original_data in staged_param_data:
                        param.data = original_data
                    staged_param_data.clear()
                if self.args.offload_train:
                    module.destroy_process_groups()

    cls.sleep = module.timer(sleep)
    cls.update_weights = module.timer(update_weights)
    cls._glm47_update_tms_scope_patched = True
    print(
        "GLM-4.7 colocate: process-group reload and LoRA sync share one live TMS pool",
        flush=True,
    )


def _snapshot_lora_parameters(model) -> list[tuple[Any, Any, Any]]:


    snapshots = []
    seen = set()
    for model_chunk in model:
        for name, param in model_chunk.named_parameters():
            if not _is_lora_parameter_name(name) or id(param) in seen:
                continue
            seen.add(id(param))
            snapshots.append(
                (
                    param,
                    param.detach().to(device="cpu", copy=True),
                    param.device,
                )
            )
    return snapshots


def _is_lora_parameter_name(name: str) -> bool:
    return "lora_" in name or (
        ".adapter." in name and ("linear_in" in name or "linear_out" in name)
    )


def _patch_rollout_data_dp_sharding() -> None:


    global _ROLLOUT_DP_SHARD_PATCHED
    if _ROLLOUT_DP_SHARD_PATCHED:
        return
    if os.environ.get("GLM47_DISABLE_ROLLOUT_DP_SHARD_PATCH", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return
    _ROLLOUT_DP_SHARD_PATCHED = True
    _when_imported("miles.utils.data", _apply_rollout_data_dp_sharding)


def _apply_rollout_data_dp_sharding(module) -> None:









    if getattr(module, "_glm47_rollout_dp_shard_patched", False):
        return

    def process_rollout_data(
        args,
        rollout_data_ref,
        dp_rank,
        dp_size,
        witness_info=None,
    ):
        if getattr(args, "delay_split_train_data_by_dp", False):
            raw = module.ray.get(rollout_data_ref.inner)
            if witness_info is not None:
                raw = {**raw, "seq_witness_ids": witness_info.witness_ids}
            raw = module.split_train_data_by_dp_raw(args, raw, dp_size=dp_size)
            rollout_data = raw[dp_rank]
        else:
            assert len(rollout_data_ref) == dp_size
            assert witness_info is None
            rollout_data = module.ray.get(rollout_data_ref[dp_rank].inner)

        partition = rollout_data.pop("partition")
        total_lengths = rollout_data["total_lengths"]
        module.Timer().seq_lens = total_lengths
        rollout_data["total_lengths"] = [total_lengths[i] for i in partition]
        if "raw_reward" in rollout_data:
            raw_reward = rollout_data["raw_reward"]
            rollout_data["_glm47_local_raw_reward"] = [
                raw_reward[i] for i in partition
            ]

        return rollout_data

    module.process_rollout_data = process_rollout_data
    module._glm47_rollout_dp_shard_patched = True


def _patch_correct_sample_logging() -> None:


    global _CORRECT_SAMPLE_LOG_PATCHED
    if _CORRECT_SAMPLE_LOG_PATCHED:
        return
    if os.environ.get("GLM47_DISABLE_CORRECT_SAMPLE_LOG_PATCH", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return
    _CORRECT_SAMPLE_LOG_PATCHED = True
    _when_imported(
        "miles.backends.training_utils.log_utils",
        _apply_correct_sample_logging,
    )


def _apply_correct_sample_logging(module) -> None:


    if getattr(module, "_glm47_correct_sample_log_patched", False):
        return
    original_log_rollout_data = module.log_rollout_data
    original_log_passrate = module.log_passrate

    def log_rollout_data(rollout_id, args, rollout_data) -> None:
        local_rewards = rollout_data.pop("_glm47_local_raw_reward", None)
        if local_rewards is None:
            return original_log_rollout_data(rollout_id, args, rollout_data)
        if not args.log_correct_samples:
            try:
                return original_log_rollout_data(rollout_id, args, rollout_data)
            finally:
                rollout_data["_glm47_local_raw_reward"] = local_rewards

        global_rewards = rollout_data["raw_reward"]
        rollout_data["raw_reward"] = local_rewards
        previous_log_passrate = module.log_passrate

        def log_passrate(passrate_rollout_id, passrate_args, passrate_data) -> None:
            current_rewards = passrate_data["raw_reward"]
            passrate_data["raw_reward"] = global_rewards
            try:
                original_log_passrate(
                    passrate_rollout_id,
                    passrate_args,
                    passrate_data,
                )
            finally:
                passrate_data["raw_reward"] = current_rewards

        module.log_passrate = log_passrate
        try:
            original_log_rollout_data(rollout_id, args, rollout_data)
        finally:
            module.log_passrate = previous_log_passrate
            rollout_data["raw_reward"] = global_rewards
            rollout_data["_glm47_local_raw_reward"] = local_rewards

    module.log_rollout_data = log_rollout_data
    module._glm47_correct_sample_log_patched = True


def _dump_sync_metrics(updater, hf_named_tensors, out_dir) -> None:

    import hashlib
    import json
    import os as _os

    try:
        rank = int(_os.environ.get("RANK", "0"))
    except ValueError:
        rank = 0
    _os.makedirs(out_dir, exist_ok=True)
    count = getattr(updater, "_glm47_sync_count", 0) + 1
    updater._glm47_sync_count = count

    entries = {}
    digest = hashlib.sha256()
    for name, tensor in sorted(hf_named_tensors, key=lambda item: item[0]):
        t = tensor.detach().float().cpu()
        entries[name] = {
            "shape": list(t.shape),
            "sum_abs": float(t.abs().sum()),
            "max_abs": float(t.abs().max()) if t.numel() else 0.0,
            "first3": t.flatten()[:3].tolist(),
        }
        digest.update(name.encode())
        digest.update(t.numpy().tobytes())
    payload = {
        "sync": count,
        "rank": rank,
        "n_tensors": len(entries),
        "sha256": digest.hexdigest(),
        "total_sum_abs": sum(e["sum_abs"] for e in entries.values()),
        "tensors": entries,
    }
    path = _os.path.join(out_dir, f"sync{count:02d}_rank{rank}.json")
    with open(path, "w") as fh:
        json.dump(payload, fh)
    print(
        f"GLM-4.7 sync metrics: sync={count} rank={rank} tensors={len(entries)} "
        f"sha256={payload['sha256'][:16]} total_sum_abs={payload['total_sum_abs']:.3f}",
        flush=True,
    )


def _apply_sglang_lora_mtp_filter(module) -> None:
    import re

    cls = getattr(module, "UpdateWeightFromTensor", None)
    if cls is None or getattr(cls, "_glm47_mtp_filter_patched", False):
        return

    original_send = cls._send_lora_params
    layer_pattern = re.compile(r"\.layers\.(\d+)\.")

    def _send_lora_params(self, hf_named_tensors):
        sync_metrics_dir = os.environ.get("GLM47_SYNC_METRICS_DIR", "").strip()
        if sync_metrics_dir:
            _dump_sync_metrics(self, hf_named_tensors, sync_metrics_dir)
        num_layers = getattr(getattr(self, "args", None), "num_layers", None)
        if num_layers:
            kept = []
            dropped = []
            for name, tensor in hf_named_tensors:
                match = layer_pattern.search(name)
                if match and int(match.group(1)) >= num_layers:
                    dropped.append(name)
                    continue
                kept.append((name, tensor))
            if dropped and kept:
                print(
                    f"GLM-4.7 rollout LoRA sync: dropping {len(dropped)} MTP adapter tensors "
                    f"(hf layer >= {num_layers}), e.g. {dropped[0]}",
                    flush=True,
                )
                hf_named_tensors = kept
        return original_send(self, hf_named_tensors)

    cls._send_lora_params = _send_lora_params






    original_init = cls.__init__

    def __init__(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        if getattr(getattr(self, "args", None), "lora_adapter_path", None) and hasattr(self, "_lora_loaded"):
            self._lora_loaded = True

    cls.__init__ = __init__
    cls._glm47_mtp_filter_patched = True


def _patch_router_circuit_breaker() -> None:


    global _ROUTER_CB_PATCHED
    if _ROUTER_CB_PATCHED:
        return
    if os.environ.get("GLM47_DISABLE_ROUTER_CB_PATCH", "").strip().lower() in {"1", "true", "yes", "on"}:
        return
    _ROUTER_CB_PATCHED = True
    _when_imported("miles.ray.rollout.router_manager", _apply_router_cb_patch)


def _apply_router_cb_patch(module) -> None:
    _apply_router_ready_timeout_patch(module)
    router_args_cls = getattr(module, "RouterArgs", None)
    if router_args_cls is None or getattr(router_args_cls, "_glm47_cb_patched", False):
        return

    original_from_cli_args = router_args_cls.from_cli_args

    def from_cli_args(*args, **kwargs):
        router_args = original_from_cli_args(*args, **kwargs)
        router_args.disable_circuit_breaker = True
        router_args.queue_size = max(4096, int(getattr(router_args, "queue_size", 0) or 0))
        router_args.queue_timeout_secs = max(1800, int(getattr(router_args, "queue_timeout_secs", 0) or 0))
        print(
            "GLM-4.7 router patch: circuit breaker disabled, "
            f"queue_size={router_args.queue_size}, queue_timeout_secs={router_args.queue_timeout_secs}",
            flush=True,
        )
        return router_args

    router_args_cls.from_cli_args = staticmethod(from_cli_args)
    router_args_cls._glm47_cb_patched = True


def _apply_router_ready_timeout_patch(module) -> None:










    original_wait = getattr(module, "wait_for_server_ready", None)
    if original_wait is None or getattr(module, "_glm47_ready_timeout_patched", False):
        return

    def wait_for_server_ready(host, port, process=None, timeout=30):
        floor = float(os.environ.get("GLM47_ROUTER_READY_TIMEOUT_S") or 300)
        effective = max(float(timeout), floor)
        if effective != float(timeout):
            print(
                f"GLM-4.7 router patch: extending server-ready timeout {timeout}s -> {effective:g}s",
                flush=True,
            )
        return original_wait(host, port, process, timeout=effective)

    module.wait_for_server_ready = wait_for_server_ready
    module._glm47_ready_timeout_patched = True


def _patch_sglang_lora_mem_pool_ordering() -> None:












    global _SGLANG_MEM_POOL_PATCHED
    if _SGLANG_MEM_POOL_PATCHED:
        return
    if os.environ.get("GLM47_DISABLE_SGLANG_MEMPOOL_ORDER_PATCH", "").strip().lower() in {"1", "true", "yes", "on"}:
        return
    _SGLANG_MEM_POOL_PATCHED = True
    _when_imported("sglang.srt.lora.mem_pool", _apply_sglang_mem_pool_ordering)


def _apply_sglang_mem_pool_ordering(module) -> None:
    import re

    cls = getattr(module, "LoRAMemoryPool", None)
    if cls is None or getattr(cls, "_glm47_expert_order_patched", False):
        return

    original_load = cls.load_lora_weight_to_buffer
    per_expert_pattern = re.compile(r"experts\.\d+\.")

    def load_lora_weight_to_buffer(self, uid, buffer_id, lora_adapter, *args, **kwargs):
        for layer in getattr(lora_adapter, "layers", None) or []:
            weights = getattr(layer, "weights", None)
            if not isinstance(weights, dict):
                continue
            per_expert = {n: w for n, w in weights.items() if per_expert_pattern.search(n)}
            if not per_expert or len(per_expert) == len(weights):
                continue
            for name, weight in weights.items():
                if name not in per_expert:
                    per_expert[name] = weight
            layer.weights = per_expert
        return original_load(self, uid, buffer_id, lora_adapter, *args, **kwargs)

    cls.load_lora_weight_to_buffer = load_lora_weight_to_buffer
    cls._glm47_expert_order_patched = True
    print("GLM-4.7: SGLang LoRA mem-pool per-expert-first ordering active", flush=True)


def _glm47_base_mappings() -> list[Any]:
    from megatron.bridge.models.conversion.param_mapping import AutoMapping, GatedMLPMapping, QKVMapping

    param_mappings = {
        "embedding.word_embeddings.weight": "model.embed_tokens.weight",
        "decoder.final_layernorm.weight": "model.norm.weight",
        "output_layer.weight": "lm_head.weight",
        "decoder.layers.*.self_attention.linear_qkv.layer_norm_weight": "model.layers.*.input_layernorm.weight",
        "decoder.layers.*.input_layernorm.weight": "model.layers.*.input_layernorm.weight",
        "decoder.layers.*.self_attention.linear_proj.weight": "model.layers.*.self_attn.o_proj.weight",
        "decoder.layers.*.pre_mlp_layernorm.weight": "model.layers.*.post_attention_layernorm.weight",
        "decoder.layers.*.mlp.linear_fc1.layer_norm_weight": "model.layers.*.post_attention_layernorm.weight",
        "decoder.layers.*.self_attention.linear_q_down_proj.weight": "model.layers.*.self_attn.q_a_proj.weight",
        "decoder.layers.*.self_attention.linear_q_up_proj.weight": "model.layers.*.self_attn.q_b_proj.weight",
        "decoder.layers.*.self_attention.linear_q_up_proj.layer_norm_weight": "model.layers.*.self_attn.q_a_layernorm.weight",
        "decoder.layers.*.self_attention.q_layernorm.weight": "model.layers.*.self_attn.q_a_layernorm.weight",
        "decoder.layers.*.self_attention.linear_kv_down_proj.weight": "model.layers.*.self_attn.kv_a_proj_with_mqa.weight",
        "decoder.layers.*.self_attention.linear_kv_up_proj.weight": "model.layers.*.self_attn.kv_b_proj.weight",
        "decoder.layers.*.self_attention.linear_kv_up_proj.layer_norm_weight": (
            "model.layers.*.self_attn.kv_a_layernorm.weight"
        ),
        "decoder.layers.*.self_attention.kv_layernorm.weight": "model.layers.*.self_attn.kv_a_layernorm.weight",
        "decoder.layers.*.mlp.linear_fc2.weight": "model.layers.*.mlp.down_proj.weight",
        "decoder.layers.*.mlp.router.weight": "model.layers.*.mlp.gate.weight",
        "decoder.layers.*.mlp.router.expert_bias": "model.layers.*.mlp.gate.e_score_correction_bias",
        "decoder.layers.*.mlp.shared_experts.router.weight": "model.layers.*.mlp.shared_experts.gate.weight",
        "decoder.layers.*.mlp.shared_experts.linear_fc2.weight": (
            "model.layers.*.mlp.shared_experts.down_proj.weight"
        ),
    }

    mappings: list[Any] = [AutoMapping(megatron_param=k, hf_param=v) for k, v in param_mappings.items()]
    mappings.extend(
        [
            QKVMapping(
                megatron_param="decoder.layers.*.self_attention.linear_qkv.weight",
                q="model.layers.*.self_attn.q_proj.weight",
                k="model.layers.*.self_attn.k_proj.weight",
                v="model.layers.*.self_attn.v_proj.weight",
            ),
            QKVMapping(
                megatron_param="decoder.layers.*.self_attention.linear_qkv.bias",
                q="model.layers.*.self_attn.q_proj.bias",
                k="model.layers.*.self_attn.k_proj.bias",
                v="model.layers.*.self_attn.v_proj.bias",
            ),
            GatedMLPMapping(
                megatron_param="decoder.layers.*.mlp.linear_fc1.weight",
                gate="model.layers.*.mlp.gate_proj.weight",
                up="model.layers.*.mlp.up_proj.weight",
            ),
            GatedMLPMapping(
                megatron_param="decoder.layers.*.mlp.shared_experts.linear_fc1.weight",
                gate="model.layers.*.mlp.shared_experts.gate_proj.weight",
                up="model.layers.*.mlp.shared_experts.up_proj.weight",
            ),
            GatedMLPMapping(
                megatron_param="decoder.layers.*.mlp.experts.linear_fc1.weight*",
                gate="model.layers.*.mlp.experts.*.gate_proj.weight",
                up="model.layers.*.mlp.experts.*.up_proj.weight",
            ),
            AutoMapping(
                megatron_param="decoder.layers.*.mlp.experts.linear_fc2.weight*",
                hf_param="model.layers.*.mlp.experts.*.down_proj.weight",
            ),
        ]
    )
    return mappings


def _glm47_mtp_mappings(hf_config: Any) -> list[Any]:
    from megatron.bridge.models.conversion.param_mapping import AutoMapping, GatedMLPMapping

    num_mtp_layers = getattr(hf_config, "num_nextn_predict_layers", 0) or 0
    num_transformer_layers = hf_config.num_hidden_layers
    mappings: list[Any] = []
    for mtp_layer in range(num_mtp_layers):
        hf_layer = mtp_layer + num_transformer_layers
        for layer_prefix in ("mtp_model_layer", "transformer_layer"):
            megatron_prefix = f"mtp.layers.{mtp_layer}.{layer_prefix}"
            hf_prefix = f"model.layers.{hf_layer}"
            mappings.extend(
                [
                    AutoMapping(
                        megatron_param=f"{megatron_prefix}.input_layernorm.weight",
                        hf_param=f"{hf_prefix}.input_layernorm.weight",
                    ),
                    AutoMapping(
                        megatron_param=f"{megatron_prefix}.self_attention.linear_proj.weight",
                        hf_param=f"{hf_prefix}.self_attn.o_proj.weight",
                    ),
                    AutoMapping(
                        megatron_param=f"{megatron_prefix}.pre_mlp_layernorm.weight",
                        hf_param=f"{hf_prefix}.post_attention_layernorm.weight",
                    ),
                    AutoMapping(
                        megatron_param=f"{megatron_prefix}.self_attention.linear_q_down_proj.weight",
                        hf_param=f"{hf_prefix}.self_attn.q_a_proj.weight",
                    ),
                    AutoMapping(
                        megatron_param=f"{megatron_prefix}.self_attention.linear_q_up_proj.weight",
                        hf_param=f"{hf_prefix}.self_attn.q_b_proj.weight",
                    ),
                    AutoMapping(
                        megatron_param=f"{megatron_prefix}.self_attention.linear_q_up_proj.layer_norm_weight",
                        hf_param=f"{hf_prefix}.self_attn.q_a_layernorm.weight",
                    ),
                    AutoMapping(
                        megatron_param=f"{megatron_prefix}.self_attention.linear_kv_down_proj.weight",
                        hf_param=f"{hf_prefix}.self_attn.kv_a_proj_with_mqa.weight",
                    ),
                    AutoMapping(
                        megatron_param=f"{megatron_prefix}.self_attention.linear_kv_up_proj.weight",
                        hf_param=f"{hf_prefix}.self_attn.kv_b_proj.weight",
                    ),
                    AutoMapping(
                        megatron_param=f"{megatron_prefix}.self_attention.linear_kv_up_proj.layer_norm_weight",
                        hf_param=f"{hf_prefix}.self_attn.kv_a_layernorm.weight",
                    ),
                    AutoMapping(
                        megatron_param=f"{megatron_prefix}.mlp.linear_fc2.weight",
                        hf_param=f"{hf_prefix}.mlp.down_proj.weight",
                    ),
                    AutoMapping(
                        megatron_param=f"{megatron_prefix}.mlp.router.weight",
                        hf_param=f"{hf_prefix}.mlp.gate.weight",
                    ),
                    AutoMapping(
                        megatron_param=f"{megatron_prefix}.mlp.router.expert_bias",
                        hf_param=f"{hf_prefix}.mlp.gate.e_score_correction_bias",
                    ),
                    GatedMLPMapping(
                        megatron_param=f"{megatron_prefix}.mlp.shared_experts.linear_fc1.weight",
                        gate=f"{hf_prefix}.mlp.shared_experts.gate_proj.weight",
                        up=f"{hf_prefix}.mlp.shared_experts.up_proj.weight",
                    ),
                    AutoMapping(
                        megatron_param=f"{megatron_prefix}.mlp.shared_experts.linear_fc2.weight",
                        hf_param=f"{hf_prefix}.mlp.shared_experts.down_proj.weight",
                    ),
                    GatedMLPMapping(
                        megatron_param=f"{megatron_prefix}.mlp.experts.linear_fc1.weight*",
                        gate=f"{hf_prefix}.mlp.experts.*.gate_proj.weight",
                        up=f"{hf_prefix}.mlp.experts.*.up_proj.weight",
                    ),
                    AutoMapping(
                        megatron_param=f"{megatron_prefix}.mlp.experts.linear_fc2.weight*",
                        hf_param=f"{hf_prefix}.mlp.experts.*.down_proj.weight",
                    ),
                ]
            )
    return mappings
