from typing import List, Optional, Union

import torch
import torch.nn as nn
from omegaconf import ListConfig
from taming.modules.losses.lpips import LPIPS

from ...util import append_dims, instantiate_from_config


class StandardDiffusionLoss(nn.Module):
    def __init__(
        self,
        sigma_sampler_config,
        type="l2",
        offset_noise_level=0.0,
        offset_noise_varying_dim = 1,
        batch2model_keys: Optional[Union[str, List[str], ListConfig]] = None,
    ):
        super().__init__()

        assert type in ["l2", "l1", "lpips"]

        self.sigma_sampler = instantiate_from_config(sigma_sampler_config)

        self.type = type
        self.offset_noise_level = offset_noise_level
        self.offset_noise_varying_dim = offset_noise_varying_dim

        if type == "lpips":
            self.lpips = LPIPS().eval()

        if not batch2model_keys:
            batch2model_keys = []

        if isinstance(batch2model_keys, str):
            batch2model_keys = [batch2model_keys]

        self.batch2model_keys = set(batch2model_keys)

    def __call__(self, network, denoiser, conditioner, input, batch):
        cond = conditioner(batch)
        additional_model_inputs = {
            key: batch[key] for key in self.batch2model_keys.intersection(batch)
        }

        sigmas = self.sigma_sampler(input.shape[0]).to(input.device)
        noise = torch.randn_like(input)
        if self.offset_noise_level > 0.0:
                # noise = noise + self.offset_noise_level * append_dims(
                #     torch.randn(input.shape[0], device=input.device), input.ndim
                # )
                assert input.ndim > self.offset_noise_varying_dim, 'input.ndim should be larger than self.offset_noise_varying_dim'
                noise = noise + self.offset_noise_level * append_dims(
                    torch.randn(input.shape[:self.offset_noise_varying_dim], device=input.device), input.ndim
                )
                
        noised_input = input + noise * append_dims(sigmas, input.ndim)
        # noised_input: [1, 4, 9, 40, 40]
        # cond['crossattn']: [1, 77, 1024]
        # sigmas: the coefficient of the corresponding t. 
        # import torchvision, einops
        # vis = einops.rearrange(input, '1 c t h w -> t c h w')[:,:3]
        # torchvision.utils.save_image(vis, 'input.png', normalize=True)
        # import pdb; pdb.set_trace()
        # model_output = denoiser(
        #     network, noised_input, sigmas, cond, **additional_model_inputs
        # )
        model_output = denoiser(network, noised_input, sigmas, cond)
        w = append_dims(denoiser.w(sigmas), input.ndim)
        return self.get_loss(model_output, input, w)

    def get_loss(self, model_output, target, w):
        if self.type == "l2":
            return torch.mean(
                (w * (model_output - target) ** 2).reshape(target.shape[0], -1), 1
            )
        elif self.type == "l1":
            return torch.mean(
                (w * (model_output - target).abs()).reshape(target.shape[0], -1), 1
            )
        elif self.type == "lpips":
            loss = self.lpips(model_output, target).reshape(-1)
            return loss