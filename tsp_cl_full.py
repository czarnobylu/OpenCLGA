import os
import math
import random
import pyopencl as cl
import numpy
import sys
from time import time
from time import clock
from itertools import tee
from pyopencl import array as clarray
from utils import create_chromosomes_by_cityids, custom_mutate, custom_crossover,\
                calc_spherical_distance, calc_linear_distance
from algorithm import BaseGeneticAlgorithm
from pprint import pprint

class TSPGACL(BaseGeneticAlgorithm):
    def __init__(self, city_info, chromosomes):
        BaseGeneticAlgorithm.__init__(self, chromosomes)
        self.city_info = city_info
        self.city_points = list(city_info.values())

        self.ctx = cl.create_some_context()
        self.queue = cl.CommandQueue(self.ctx)
        f = open('kernel/tsp_cl_full_float.c', 'r')
        fstr = "".join(f.readlines())
        f.close()
        self.mem_pool =cl.tools.MemoryPool(cl.tools.ImmediateAllocator(self.queue))

        strInc = '-I '
        modifiedlstPath = []
        for path in ["kernel"]:
            escapedPath = path.replace(' ', '^ ') if sys.platform.startswith('win') else path.replace(' ', '\\ ')
            modifiedlstPath.append(strInc + escapedPath)
        self.prg = cl.Program(self.ctx, fstr).build(modifiedlstPath);

        pointType = numpy.dtype([('x', numpy.float32), ('y', numpy.float32)])
        # Add a duplicated city_point[0] in front of the list of city_points.
        # Makes it easier to access for kernel.
        expanded_city_points = [self.city_points[0]] + self.city_points
        self.dev_points = clarray.to_device(self.queue,
                                            numpy.array(expanded_city_points, dtype=pointType),
                                            allocator=self.mem_pool)

        self.set_customized_crossover_func(custom_crossover)
        self.set_customized_mutate_func(custom_mutate)
        self.set_customized_run_impl(self.run_impl)

    def evaluate_fitness(self, chromosomes):
        pass

    def run_impl(self, generations, prob_mutate, prob_crossover):
        lenght_of_chromosome = 0
        chromosomesArray = []
        chromosomes = self.get_chromosomes()
        for c in chromosomes:
            if lenght_of_chromosome == 0:
                lenght_of_chromosome = c.num_of_genes
            # Each chromosome's length should be the same
            assert lenght_of_chromosome == c.num_of_genes
            for g in c.dna:
                chromosomesArray += g
            chromosomesArray += c.dna[0]

        num_of_chromosomes = len(chromosomes)
        distances = numpy.zeros(num_of_chromosomes, dtype=numpy.float32)
        survivors = numpy.zeros(num_of_chromosomes, dtype=numpy.bool)
        np_chromosomes = numpy.array(chromosomesArray, dtype=numpy.int32)

        mf = cl.mem_flags
        # Random number should be given by Host program because OpenCL doesn't have a random number
        # generator. We just include one, Noise.cl.
        rnum = [random.randint(1, (int)(time()))]
        dev_rnum = cl.Buffer(self.ctx, mf.READ_WRITE | mf.COPY_HOST_PTR,
                             hostbuf=numpy.array(rnum, dtype=numpy.int32))


        dev_chromosomes = cl.Buffer(self.ctx, mf.READ_WRITE | mf.COPY_HOST_PTR,
                                    hostbuf=np_chromosomes)
        dev_distances = cl.Buffer(self.ctx, mf.WRITE_ONLY, distances.nbytes)
        dev_survivors = cl.Buffer(self.ctx, mf.WRITE_ONLY, survivors.nbytes)

        cl.enqueue_copy(self.queue, dev_distances, distances)

        exec_evt = None
        for i in range(generations):
            exec_evt = self.prg.tsp_one_generation(self.queue,
                                                   (num_of_chromosomes,),
                                                   (num_of_chromosomes,),
                                                   self.dev_points.data,
                                                   dev_chromosomes,
                                                   dev_distances,
                                                   dev_survivors,
                                                   dev_rnum,
                                                   numpy.int32(len(self.city_points)+1),
                                                   numpy.int32(num_of_chromosomes),
                                                   numpy.float32(prob_mutate),
                                                   numpy.float32(prob_crossover))
        if exec_evt:
            exec_evt.wait()
        cl.enqueue_read_buffer(self.queue, dev_distances, distances)
        cl.enqueue_read_buffer(self.queue, dev_chromosomes, np_chromosomes).wait()

        minDistance = min(value for value in distances)
        minIndex = list(distances).index(minDistance)
        print("Shortest Length: %f @ %d"%(minDistance, minIndex))

        # We had convert chromosome to a cyclic gene. So, the num_of_genes in CL is more than python
        # by one.
        startGeneId = minIndex * (chromosomes[0].num_of_genes + 1)
        endGeneId = (minIndex + 1) * (chromosomes[0].num_of_genes + 1)
        print("Shortest Path: " + " => ".join(str(v) for v in np_chromosomes[startGeneId:endGeneId]))
        print(">>>>>>>>>>>>>>>>>>>>>>>>>> BYE")
        pass

def run(num_cities=20, num_chromosomes=100, generations=5000):
    random.seed(100)
    city_ids = list(range(1, num_cities + 1))
    city_info = {city_id: (random.random() * 100, random.random() * 100) for city_id in city_ids}

    rs = random.randint(1, 1)
    random.seed(rs)

    chromosomes = create_chromosomes_by_cityids(num_chromosomes, city_ids)

    tsp_ga_cl = TSPGACL(city_info, chromosomes)

    prob_mutate = 0.10
    prob_cross = 0.50
    best = tsp_ga_cl.run(generations, prob_mutate, prob_cross)

    print("run took", tsp_ga_cl.elapsed_time, "seconds")
    # print("best =", best.dna)
    # print("best distance =", tsp_ga_cl.calc_distance(best))
    # print("avg eval time :", tsp_ga_cl.get_avg_evaluation_time(), "seconds.")
if __name__ == '__main__':
    run()
