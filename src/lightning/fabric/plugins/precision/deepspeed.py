# Copyright The Lightning AI team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Generator, Literal

import torch
from lightning_utilities.core.apply_func import apply_to_collection
from torch import Tensor
from torch.nn import Module
from typing_extensions import get_args

from lightning.fabric.plugins.precision.precision import Precision
from lightning.fabric.plugins.precision.utils import _convert_fp_tensor
from lightning.fabric.utilities.types import Steppable

if TYPE_CHECKING:
    from lightning.fabric.strategies.deepspeed import _DEEPSPEED_AVAILABLE

    if _DEEPSPEED_AVAILABLE:  # type: ignore[has-type]
        import deepspeed

_PRECISION_INPUT = Literal["32-true", "16-true", "bf16-true", "16-mixed", "bf16-mixed"]


class DeepSpeedPrecision(Precision):
    """Precision plugin for DeepSpeed integration.

    Args:
        precision: Full precision (32-true), half precision (16-true, bf16-true) or
            mixed precision (16-mixed, bf16-mixed).

    Raises:
        ValueError:
            If unsupported ``precision`` is provided.
    """

    def __init__(self, precision: _PRECISION_INPUT) -> None:
        supported_precision = get_args(_PRECISION_INPUT)
        if precision not in supported_precision:
            raise ValueError(
                f"`precision={precision!r})` is not supported in DeepSpeed."
                f" `precision` must be one of: {supported_precision}."
            )
        self.precision = precision

        precision_to_type = {
            "bf16-mixed": torch.bfloat16,
            "16-mixed": torch.float16,
            "bf16-true": torch.bfloat16,
            "16-true": torch.float16,
            "32-true": torch.float32,
        }
        self._desired_dtype = precision_to_type[self.precision]

    def convert_module(self, module: Module) -> Module:
        if "true" in self.precision:
            return module.to(dtype=self._desired_dtype)
        return module

    @contextmanager
    def init_context(self) -> Generator[None, None, None]:
        default_dtype = torch.get_default_dtype()
        torch.set_default_dtype(self._desired_dtype if "true" in self.precision else default_dtype)
        yield
        torch.set_default_dtype(default_dtype)

    def convert_input(self, data: Any) -> Any:
        return apply_to_collection(data, function=_convert_fp_tensor, dtype=Tensor, dst_type=self._desired_dtype)

    def convert_output(self, data: Any) -> Any:
        return apply_to_collection(data, function=_convert_fp_tensor, dtype=Tensor, dst_type=torch.get_default_dtype())

    def backward(self, tensor: Tensor, model: "deepspeed.DeepSpeedEngine", *args: Any, **kwargs: Any) -> None:
        """Performs back-propagation using DeepSpeed's engine."""
        model.backward(tensor, *args, **kwargs)

    def optimizer_step(
        self,
        optimizer: Steppable,
        **kwargs: Any,
    ) -> Any:
        # DeepSpeed handles the optimizer step internally
        return optimizer.step(**kwargs)
