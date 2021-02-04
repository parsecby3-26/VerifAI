
"""Samplers generating points in a feature space, possibly subject to
specifications.
"""

import random
import dill
import numpy as np

from verifai.features import FilteredDomain
from verifai.samplers.domain_sampler import SplitSampler, TerminationException
from verifai.samplers.rejection import RejectionSampler
from verifai.samplers.halton import HaltonSampler
from verifai.samplers.cross_entropy import CrossEntropySampler
from verifai.samplers.random_sampler import RandomSampler
from verifai.samplers.multi_armed_bandit import MultiArmedBanditSampler
from verifai.samplers.eg_sampler import EpsilonGreedySampler
from verifai.samplers.bayesian_optimization import BayesOptSampler
from verifai.samplers.simulated_annealing import SimulatedAnnealingSampler
from verifai.samplers.grid_sampler import GridSampler

### Samplers defined over FeatureSpaces

class FeatureSampler:
    """Abstract class for samplers over FeatureSpaces."""

    def __init__(self, space):
        self.space = space

    @classmethod
    def samplerFor(cls, space):
        """Convenience function choosing a default sampler for a space."""
        return cls.randomSamplerFor(space)

    @staticmethod
    def randomSamplerFor(space):
        """Creates a random sampler for a given space"""
        return LateFeatureSampler(space, RandomSampler, RandomSampler)

    @staticmethod
    def haltonSamplerFor(space, halton_params=None):
        """Creates a Halton sampler for a given space.

        Uses random sampling for lengths of feature lists and any
        Domains that are not continous and standardizable.
        """
        def makeDomainSampler(domain):
            return SplitSampler.fromPredicate(
                domain,
                lambda d: d.standardizedDimension > 0,
                lambda domain: HaltonSampler(domain=domain,
                                             halton_params=halton_params),
                makeRandomSampler)
        return LateFeatureSampler(space, RandomSampler, makeDomainSampler)

    @staticmethod
    def crossEntropySamplerFor(space, ce_params):
        """Creates a cross-entropy sampler for a given space.

        Uses random sampling for lengths of feature lists and any Domains
        that are not standardizable."""
        return LateFeatureSampler(space, RandomSampler,
            lambda domain: CrossEntropySampler(domain=domain,
                                               ce_params=ce_params))

    @staticmethod
    def epsilonGreedySamplerFor(space, ce_params):
        """Creates a cross-entropy sampler for a given space.

        Uses random sampling for lengths of feature lists and any Domains
        that are not standardizable."""
        return LateFeatureSampler(space, RandomSampler,
            lambda domain: EpsilonGreedySampler(domain=domain,
                                               ce_params=ce_params))

    @staticmethod
    def multiArmedBanditSamplerFor(space, ce_params):
        """Creates a multi-armed bandit sampler for a given space.

        Uses random sampling for lengths of feature lists and any Domains
        that are not standardizable."""
        return LateFeatureSampler(space, RandomSampler,
            lambda domain: MultiArmedBanditSampler(domain=domain,
                                               ce_params=ce_params))

    @staticmethod
    def gridSamplerFor(space, grid_params=None):
        """Creates a grid sampler for a given space.

        Uses random sampling for lengths of feature lists and any Domains
        that are not standardizable."""

        def makeDomainSampler(domain):
            return SplitSampler.fromPredicate(
                domain,
                lambda d: d.isStandardizable,
                lambda domain: GridSampler(domain=domain,
                                           grid_params=grid_params),
                makeRandomSampler)
        return LateFeatureSampler(space, RandomSampler, makeDomainSampler)

    @staticmethod
    def simulatedAnnealingSamplerFor(space, sa_params):
        """Creates a cross-entropy sampler for a given space.

        Uses random sampling for lengths of feature lists and any Domains
        that are not continuous and standardizable."""
        def makeDomainSampler(domain):
            return SplitSampler.fromPredicate(
                domain,
                lambda d: d.standardizedDimension > 0,
                lambda domain: SimulatedAnnealingSampler(domain=domain,
                                                         sa_params=sa_params),
                makeRandomSampler)
        return LateFeatureSampler(space, RandomSampler, makeDomainSampler)

    @staticmethod
    def bayesianOptimizationSamplerFor(space, BO_params):
        """Creates a Bayesian Optimization sampler for a given space.

        Uses random sampling for lengths of feature lists and any
        Domains that are not continous and standardizable.
        """
        def makeDomainSampler(domain):
            return SplitSampler.fromPredicate(
                domain,
                lambda d: d.standardizedDimension > 0,
                lambda domain: BayesOptSampler(domain=domain,
                                               BO_params=BO_params),
                makeRandomSampler)
        return LateFeatureSampler(space, RandomSampler, makeDomainSampler)

    def getSample(self):
        """Generate the next sample, given the current distribution."""
        return self.nextSample(feedback=None)
    
    def update(self, sample, info, rho):
        """Use the provided sample and rho value to update the state of the sampler."""
        pass

    def nextSample(self, feedback=None):
        """Generate the next sample, given feedback from the last sample."""
        raise NotImplementedError('tried to use abstract FeatureSampler')

    def saveToFile(self, path):
        with open(path, 'wb') as outfile:
            randState = random.getstate()
            numpyRandState = np.random.get_state()
            allState = (randState, numpyRandState, self)
            dill.dump(allState, outfile)

    @staticmethod
    def restoreFromFile(path):
        with open(path, 'rb') as infile:
            allState = dill.load(infile)
            randState, numpyRandState, sampler = allState
            random.setstate(randState)
            np.random.set_state(numpyRandState)
            return sampler

    def __iter__(self):
        try:
            feedback = None
            while True:
                feedback = yield self.nextSample(feedback)
        except TerminationException:
            return

class LateFeatureSampler(FeatureSampler):
    """FeatureSampler that works by first sampling only lengths of feature
    lists, then sampling from the resulting fixed-dimensional Domain.

    e.g. LateFeatureSampler(space, RandomSampler, HaltonSampler) creates a
    FeatureSampler which picks lengths uniformly at random and applies
    Halton sampling to each fixed-length space.
    """

    def __init__(self, space, makeLengthSampler, makeDomainSampler):
        super().__init__(space)
        lengthDomain, fixedDomains = space.domains
        if lengthDomain is None:    # space has no feature lists
            self.lengthSampler = None
            self.domainSampler = makeDomainSampler(fixedDomains)
        else:
            self.lengthDomain = lengthDomain
            self.lengthSampler = makeLengthSampler(lengthDomain)
            self.domainSamplers = {
                point: makeDomainSampler(domain)
                for point, domain in fixedDomains.items()
            }
            self.feedbacks = { length: None for length in fixedDomains }
            self.lastLength = None

    def nextSample(self, feedback=None):
        if self.lengthSampler is None:
            domainPoint, info = self.domainSampler.nextSample(feedback)
            # print(f'domainPoint = {domainPoint}')
        else:
            if self.lastLength is not None:
                self.feedbacks[self.lastLength] = feedback
            length, info1 = self.lengthSampler.nextSample(feedback)
            self.lastLength = length
            lastFeedback = self.feedbacks[length]
            domainPoint, info2 = self.domainSamplers[length].nextSample(lastFeedback)
            info = (info1, info2)
        return self.space.makePoint(*domainPoint), info
    
    def getSample(self):
        if self.lengthSampler is None:
            domainPoint, info = self.domainSampler.getSample()
            # print(f'domainPoint = {domainPoint}')
        else:
            length, info1 = self.lengthSampler.getSample()
            self.lastLength = length
            lastFeedback = self.feedbacks[length]
            domainPoint, info2 = self.domainSamplers[length].nextSample(lastFeedback)
            info = (info1, info2)
        return self.space.makePoint(*domainPoint), info
    
    def update(self, sample, info, rho):
        if self.lengthSampler is None:
            self.domainSampler.update(sample, info, rho)
        else:
            self.lengthSampler.update(sample, info[0], rho)
            lengths = []
            for name, feature in self.space.namedFeatures:
                if feature.lengthDomain:
                    lengths.append(len(getattr(sample, name)))
            lengthPoint = self.lengthDomain.makePoint(*lengths)
            self.domainSamplers[lengthPoint].update(sample, info[1], rho)

### Utilities

def makeRandomSampler(domain):
    """Utility function making a random sampler for a domain."""
    sampler = RandomSampler(domain)
    if domain.requiresRejection:
        sampler = RejectionSampler(sampler)
    return sampler
