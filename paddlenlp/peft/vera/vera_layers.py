# Copyright (c) 2023 PaddlePaddle Authors. All Rights Reserved.
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

import math
from typing import List, Optional

import paddle
import paddle.nn as nn
import paddle.nn.functional as F
from paddle.distributed.fleet.layers.mpu import mp_ops



class VeRALinear(nn.Linear):
    # VeRA implemented in a dense layer
    def __init__(
        self,
        base_linear_module: paddle.nn.layer.common.Linear,
        in_features: int,
        out_features: int,
        r: int = 0,
        vera_alpha: int = 1,
        vera_dropout: float = 0.0,
        merge_weights: bool = True,
        pissa_init : bool = False,
        **kwargs
    ):
        nn.Linear.__init__(self, in_features, out_features, **kwargs)
        self.weight.set_value(base_linear_module.weight)
        
        if not isinstance(r, int) or r <= 0:
            raise ValueError("Lora rank r should be a positive integer")
        self.r = r
        self.vera_alpha = vera_alpha
        # Optional dropout
        if vera_dropout > 0.0:
            self.vera_dropout = nn.Dropout(p=vera_dropout)
        else:
            self.vera_dropout = lambda x: x
        # Mark the weight as unmerged
        self.merged = False
        self.merge_weights = merge_weights

        if pissa_init:
            assert self.vera_alpha == self.r, "pissa method requires vera_alpha=r, scaling=1"
            self.scaling = 1.0
            self.lora_A = self.create_parameter(
                shape=[in_features, r],
                dtype=self._dtype,
                is_bias=False,
            )
            self.lora_B = self.create_parameter(
                shape=[r, out_features],
                dtype=self._dtype,
                is_bias=False,
            )
            self.pissa_init(r)

        else:
            # Actual trainable parameters
            self.lora_A = self.create_parameter(
                shape=[in_features, r],
                dtype=self._dtype,
                is_bias=False,
                default_initializer=nn.initializer.KaimingUniform(negative_slope=math.sqrt(5), nonlinearity="leaky_relu"),
            )
            self.lora_B = self.create_parameter(
                shape=[r, out_features],
                dtype=self._dtype,
                is_bias=False,
                default_initializer=nn.initializer.Constant(value=0.0),
            )
        self.scaling = self.vera_alpha / self.r
        
        self.vera_b = self.create_parameter(
                shape=[out_features],
                dtype=self._dtype,
                is_bias=False,
                default_initializer=nn.initializer.Constant(value=1.0),
        )
        
        self.vera_d = self.create_parameter(
                shape=[r],
                dtype=self._dtype,
                is_bias=False,
                default_initializer=nn.initializer.Constant(value=1.0),
        )

        # Freezing the pre-trained weight matrix and bias vector
        self.weight.stop_gradient = True

        

    def pissa_init(self, r):
        weight = self.weight
        dtype = weight.dtype

        if dtype != paddle.float32:
            weight = weight.astype(paddle.float32)

        U, S, Vh = paddle.linalg.svd(weight.data, full_matrices=False)
        
        Ur = U[:, :r]
        Sr = S[:r]
        Vhr = Vh[:r]
        
        lora_A = (Ur @ paddle.diag(paddle.sqrt(Sr)))
        lora_B = (paddle.diag(paddle.sqrt(Sr)) @ Vhr)

        self.lora_A.set_value(lora_A.astype(dtype))
        self.lora_B.set_value(lora_B.astype(dtype))
        res = weight.data - lora_A @ lora_B
        weight = res.astype(dtype)
        self.weight.set_value(weight) 
        

    def train(self):
        super().train()
        if self.merge_weights and self.merged:
            # Make sure that the weights are not merged
            diag_b = paddle.diag(self.vera_b)
            diag_d = paddle.diag(self.vera_d)
            new_weight = self.weight - self.lora_A @ diag_d @ self.lora_B @ diag_b * self.scaling
            self.weight.set_value(new_weight)
            self.merged = False

    def eval(self):
        super().eval()
        if self.merge_weights and not self.merged:
            # Merge the weights and mark it
            diag_b = paddle.diag(self.vera_b)
            diag_d = paddle.diag(self.vera_d)
            new_weight = self.weight + self.lora_A @ diag_d @ self.lora_B @ diag_b * self.scaling
            self.weight.set_value(new_weight)
            self.merged = True

    def forward(self, input: paddle.Tensor, *args, **kwargs):
        result = F.linear(x=input, weight=self.weight, bias=self.bias, name=self.name)
        if not self.merged:
            # result += (self.vera_dropout(input) @ self.lora_A @ self.lora_B) * self.scaling
            diag_b = paddle.diag(self.vera_b)
            diag_d = paddle.diag(self.vera_d)
            result += (self.vera_dropout(input) @ self.lora_A @ diag_d @ self.lora_B @ diag_b) * self.scaling
        return result

    def extra_repr(self):
        name = f", name={self.name}" if self.name else ""
        return f"in_features={self.weight.shape[0]}, out_features={self.weight.shape[1]}, rank={self.r}{name}"


