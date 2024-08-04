# Copyright (c) 2024 PaddlePaddle Authors. All Rights Reserved.
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

import logging

import paddlenlp.peft.reft.pavenv as pv


# Count parameters of a model that require gradients
def count_parameters(model):
    return int(sum(p.numel() for p in model.parameters() if not p.stop_gradient))


# Base model for Reft methods.
class ReftModel(pv.IntervenableModel):
    def __init__(self, config, model, **kwargs):
        super().__init__(config, model, **kwargs)

    @staticmethod
    def load(reft_checkpoint_dir, model):
        model = pv.IntervenableModel.load(reft_checkpoint_dir, model)
        return model

    def print_trainable_parameters(self):
        trainable_intervention_parameters = 0
        for k, v in self.interventions.items():
            trainable_intervention_parameters += count_parameters(v[0])

        trainable_model_parameters = int(sum(p.numel() for p in self.model.parameters() if not p.stop_gradient))

        all_model_parameters = int(sum(p.numel() for p in self.model.parameters()))

        total_trainable_parameters = trainable_intervention_parameters + trainable_model_parameters

        logging.info("trainable_intervention_parameters:", trainable_intervention_parameters)
        logging.info("trainable_model_parameters:", trainable_model_parameters)
        logging.info("all_model_parameters:", all_model_parameters)
        logging.info("total_trainable_parameters:", total_trainable_parameters)
        logging.info(
            f"trainable intervention params: {trainable_intervention_parameters:,d} || trainable model params: {trainable_model_parameters:,d}\n"
            f"model params: {all_model_parameters:,d} || trainable%: {100 * total_trainable_parameters / all_model_parameters}"
        )
