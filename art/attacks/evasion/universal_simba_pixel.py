# MIT License
#
# Copyright (C) IBM Corporation 2018
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
# Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
# WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
# TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""
This module implements the black-box attack `simba`.

| Paper link: https://arxiv.org/abs/1905.07121
"""
from __future__ import absolute_import, division, print_function, unicode_literals

import logging

import numpy as np

from art.config import ART_NUMPY_DTYPE
from art.classifiers.classifier import ClassifierGradients
from art.attacks.attack import EvasionAttack
from art.utils import compute_success
from art.utils import projection

logger = logging.getLogger(__name__)


class Universal_SimBA_pixel(EvasionAttack):
    attack_params = EvasionAttack.attack_params + ['max_iter', 'epsilon', 'order', 'delta', 'eps', 'norm', 'batch_size']

    def __init__(self, classifier, max_iter=3000, epsilon=0.1, order='random', delta=0.1, eps=10.0, norm=2, batch_size=1):
        """
        Create a universal SimBA (pixel) attack instance.

        :param classifier: A trained classifier.
        :type classifier: :class:`.Classifier`
        :param max_iter: The maximum number of iterations.
        :type max_iter: `int`
        :param epsilon: Overshoot parameter.
        :type epsilon: `float`
        :param order: The attack order
        :type order: `str`
        :param delta: desired accuracy
        :type delta: `float`
        :param eps: Attack step size (input variation)
        :type eps: `float`
        :param norm: The norm of the adversarial perturbation. Possible values: np.inf, 2
        :type norm: `int`
        :param batch_size: Batch size (but, batch process unavailable in this implementation)
        :type batch_size: `int`
        """
        super(Universal_SimBA_pixel, self).__init__(classifier=classifier)
        if not isinstance(classifier, ClassifierGradients):
            raise (TypeError('For `' + self.__class__.__name__ + '` classifier must be an instance of '
                             '`art.classifiers.classifier.ClassifierGradients`, the provided classifier is instance of '
                             + str(classifier.__class__.__bases__) + '. '
                             ' The classifier needs to be a Neural Network and provide gradients.'))

        params = {'max_iter': max_iter, 'epsilon': epsilon, 'order': order, 'delta': delta, 'eps': eps, 'norm': norm, 'batch_size': batch_size}
        self.set_params(**params)

    def generate(self, x, y=None, **kwargs):
        """
        Generate adversarial samples and return them in an array.

        :param x: An array with the original inputs to be attacked.
        :type x: `np.ndarray`
        :param y: An array with the original labels to be predicted.
        :type y: `np.ndarray`
        :return: An array holding the adversarial examples.
        :rtype: `np.ndarray`
        """
        x = x.astype(ART_NUMPY_DTYPE)
        nb_instances = x.shape[0]
        preds = self.classifier.predict(x, batch_size=self.batch_size)
        if y is None:
            y = np.argmax(preds, axis=1)
        original_labels = y
        current_labels = original_labels
        last_probs = preds[(range(nb_instances),original_labels)]

        n_dims = np.prod(x[0].shape)
        if self.order == "diag" or self.order == "perm":
            if self.max_iter > n_dims:
                self.max_iter = n_dims
                logger.info('`max_iter` was reset to %d because it needs to be #pixels x #channels or less for `order` of %s', n_dims, self.order)
        else:
            actual_max_iter = self.max_iter

        if self.order == "diag":
            indices = self.diagonal_order(x.shape[2], 3)[:self.max_iter]
        elif self.order == "perm":
            indices = np.random.permutation(n_dims)

        clip_min = -np.inf
        clip_max = np.inf 
        if hasattr(self.classifier, 'clip_values') and self.classifier.clip_values is not None:
            clip_min, clip_max = self.classifier.clip_values

        fooling_rate = 0.0
        nb_iter = 0
        noise = 0
        while fooling_rate < 1. - self.delta and nb_iter < self.max_iter:
            diff = np.zeros(n_dims)
            if self.order == "random":
                diff[np.random.choice(range(n_dims))] = self.epsilon
            elif self.order == "diag":
                diff[indices[nb_iter]] = self.epsilon
            elif self.order == "perm":
                diff[indices[nb_iter]] = self.epsilon

            left_noise = noise - diff.reshape(x[0][None, ...].shape)
            left_noise = projection(left_noise, self.eps, self.norm)

            left_preds = self.classifier.predict(np.clip(x + left_noise, clip_min, clip_max), batch_size=self.batch_size)
            left_probs = left_preds[(range(nb_instances),original_labels)]

            right_noise = noise + diff.reshape(x[0][None, ...].shape)
            right_noise = projection(right_noise, self.eps, self.norm)

            right_preds = self.classifier.predict(np.clip(x + right_noise, clip_min, clip_max), batch_size=self.batch_size)
            right_probs = right_preds[(range(nb_instances),original_labels)]

            if np.sum(left_probs - last_probs) < 0.0:
                if np.sum(left_probs - right_probs) < 0.0:
                    last_probs = left_probs
                    noise = left_noise
                    current_labels = np.argmax(left_preds, axis=1)
                else:
                    last_probs = right_probs
                    noise = right_noise
                    current_labels = np.argmax(right_preds, axis=1)
            else:
                if np.sum(right_probs - last_probs) < 0.0:
                    last_probs = right_probs
                    noise = right_noise
                    current_labels = np.argmax(right_preds, axis=1)
            
            # Compute the error rate
            fooling_rate = np.sum(original_labels != current_labels) / nb_instances
            
            nb_iter = nb_iter + 1

            if nb_iter % 10 == 0:
                val_norm = np.linalg.norm(noise.flatten(), ord=self.norm)
                logger.info('Fooling rate of Universal SimBA (pixel) attack at %d iterations: %.2f%% (L%d norm of noise: %.2f)', nb_iter, 100 * fooling_rate, self.norm, val_norm)

        logger.info('Final fooling rate of Universal SimBA (pixel) attack: %.2f%%', 100 * fooling_rate)
        return x + noise


    def set_params(self, **kwargs):
        """
        Take in a dictionary of parameters and applies attack-specific checks before saving them as attributes.

        :param max_iter: The maximum number of iterations.
        :type max_iter: `int`
        :param epsilon: Overshoot parameter.
        :type epsilon: `float`
        :param order: The attack order
        :type order: `str`
        :param delta: desired accuracy
        :type delta: `float`
        :param eps: Attack step size (input variation)
        :type eps: `float`
        :param norm: The norm of the adversarial perturbation. Possible values: np.inf, 2
        :type norm: `int`
        :param batch_size: Internal size of batches on which adversarial samples are generated.
        :type batch_size: `int`
        """
        # Save attack-specific parameters
        super(Universal_SimBA_pixel, self).set_params(**kwargs)

        if not isinstance(self.max_iter, (int, np.int)) or self.max_iter <= 0:
            raise ValueError("The number of iterations must be a positive integer.")

        if self.epsilon < 0:
            raise ValueError("The overshoot parameter must not be negative.")
        
        if not isinstance(self.delta, (float, int)) or self.delta < 0 or self.delta > 1:
            raise ValueError("The desired accuracy must be in the range [0, 1].")

        if not isinstance(self.eps, (float, int)) or self.eps <= 0:
            raise ValueError("The eps coefficient must be a positive float.")

        if self.batch_size <= 0:
            raise ValueError('The batch size `batch_size` has to be positive.')
        
        if self.order != "random" and self.order != "perm" and self.order != "diag":
            raise ValueError('The attack `order` has to be `random`, `perm`, or `diag`')

        return True

    def diagonal_order(self, image_size, channels):
        x = np.arange(0, image_size).cumsum()
        order = np.zeros((image_size, image_size))
        for i in range(image_size):
            order[i, :(image_size - i)] = i + x[i:]
        for i in range(1, image_size):
            reverse = order[image_size - i - 1].take([i for i in range(i-1, -1, -1)])
            order[i, (image_size - i):] = image_size * image_size - 1 - reverse
        if channels > 1:
            order_2d = order
            order = np.zeros((channels, image_size, image_size))
            for i in range(channels):
                order[i, :, :] = 3 * order_2d + i
        return order.transpose(1,2,0).reshape(1, -1).squeeze().argsort()