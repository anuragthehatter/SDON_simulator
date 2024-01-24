# Standard library imports
import os
import signal
import json

# Third party library imports
import networkx as nx
import numpy as np

# Local application imports
from sim_scripts.request_generator import get_requests
from sim_scripts.sdn_controller import SDNController
from helper_scripts.ai_helpers import AIMethods
from helper_scripts.stats_helpers import SimStats


# TODO: No support for AI in all scripts for the time being
class Engine:
    """
    Controls a single simulation.
    """

    def __init__(self, **kwargs):
        self.engine_props = kwargs['properties']

        # The network spectrum database
        self.net_spec_dict = dict()
        # Contains the requests generated in a simulation
        self.reqs_dict = None
        # Holds relevant information of requests that have been ALLOCATED in a simulation, used for debugging
        self.reqs_status_dict = dict()

        self.iteration = 0
        self.topology = nx.Graph()
        # For the purposes of saving simulation output data
        self.sim_info = os.path.join(self.engine_props['network'], self.engine_props['date'],
                                     self.engine_props['sim_start'])

        self.sdn_obj = SDNController(engine_props=self.engine_props)
        self.stats_obj = SimStats(engine_props=self.engine_props, sim_info=self.sim_info)
        self.ai_obj = AIMethods(properties=self.engine_props)

    def update_ai_obj(self, sdn_dict: dict):
        """
        Updates the artificial intelligent object class after each request.
        
        :param sdn_dict: The data that was retrieved from the SDN controller.
        """
        if self.engine_props['route_method'] == 'ai':
            if not sdn_dict['was_routed']:
                routed = False
                spectrum = {}
                path_mod = ''
            else:
                spectrum = sdn_dict['spectrum_dict']
                routed = True
                path_mod = sdn_dict['spectrum_dict']['mod_format']

            self.ai_obj.update(routed=routed, spectrum=spectrum, path_mod=path_mod)

    def handle_arrival(self, curr_time: float):
        """
        Updates the SDN controller to handle an arrival request and retrieves relevant request statistics.

        :param curr_time: The arrival time of the request.
        """
        for req_key, req_value in self.reqs_dict[curr_time].items():
            self.sdn_obj.sdn_props[req_key] = req_value

        self.sdn_obj.handle_event(request_type='arrival')
        self.net_spec_dict = self.sdn_obj.sdn_props['net_spec_dict']

        self.update_ai_obj(sdn_dict=self.sdn_obj.sdn_props)
        self.stats_obj.iter_update(req_data=self.reqs_dict[curr_time], sdn_data=self.sdn_obj.sdn_props)

        if self.sdn_obj.sdn_props['was_routed']:
            self.stats_obj.curr_trans = self.sdn_obj.sdn_props['num_trans']

            self.reqs_status_dict.update({self.reqs_dict[curr_time]['req_id']: {
                "mod_format": self.sdn_obj.sdn_props['spectrum_dict']['modulation'],
                "path": self.sdn_obj.sdn_props['path_list'],
                "is_sliced": self.sdn_obj.sdn_props['is_sliced'],
                "was_routed": self.sdn_obj.sdn_props['was_routed'],
            }})

    def handle_release(self, curr_time: float):
        """
        Updates the SDN controller to handle the release of a request.

        :param curr_time: The arrival time of the request.
        :return: None
        """
        for req_key, req_value in self.reqs_dict[curr_time].items():
            self.sdn_obj.sdn_props[req_key] = req_value

        if self.reqs_dict[curr_time]['req_id'] in self.reqs_status_dict:
            self.sdn_obj.sdn_props['path_list'] = self.reqs_status_dict[self.reqs_dict[curr_time]['req_id']]['path']
            self.sdn_obj.handle_event(request_type='release')
            self.net_spec_dict = self.sdn_obj.sdn_props['net_spec_dict']
        # Request was blocked, nothing to release
        else:
            pass

    def create_topology(self):
        """
        Create the physical topology of the simulation.

        :return: None
        """
        self.net_spec_dict = {}
        # Create nodes
        self.topology.add_nodes_from(self.engine_props['topology_info']['nodes'])
        # Create links
        for link_num, link_data in self.engine_props['topology_info']['links'].items():
            source = link_data['source']
            dest = link_data['destination']
            cores_matrix = np.zeros((link_data['fiber']['num_cores'], self.engine_props['spectral_slots']))

            self.net_spec_dict[(source, dest)] = {'cores_matrix': cores_matrix, 'link_num': int(link_num)}
            self.net_spec_dict[(dest, source)] = {'cores_matrix': cores_matrix, 'link_num': int(link_num)}
            self.topology.add_edge(source, dest, length=link_data['length'], nli_cost=None)

        self.engine_props['topology'] = self.topology
        self.stats_obj.topology = self.topology
        self.sdn_obj.sdn_props['net_spec_dict'] = self.net_spec_dict
        self.sdn_obj.sdn_props['topology'] = self.topology

    def generate_requests(self, seed: int):
        """
        Calls the request generator to generate requests.

        :param seed: The seed to use for the random generation.
        :return: None
        """
        self.reqs_dict = get_requests(seed=seed, engine_props=self.engine_props)
        self.reqs_dict = dict(sorted(self.reqs_dict.items()))

    def run(self):
        """
        Controls the Engine class methods.

        :return: None
        """
        self.create_topology()

        # TODO: Remove
        # with open('new_network_5090.json', 'r') as file_path:
        #     self.net_spec_dict = json.load(file_path)
        #
        # for link_tuple in self.net_spec_dict:
        #     for core_num, core_arr in enumerate(self.net_spec_dict[link_tuple]['cores_matrix']):
        #         self.net_spec_dict[link_tuple]['cores_matrix'][core_num] = np.array(core_arr)
        #
        #     self.net_spec_dict[link_tuple]['cores_matrix'] = np.array(self.net_spec_dict[link_tuple][
        #                                                                   'cores_matrix'])
        #
        # self.net_spec_dict = {eval(key): value for key, value in self.net_spec_dict.items()}
        #
        # self.sdn_obj.sdn_props['net_spec_dict'] = self.net_spec_dict
        # TODO: End remove


        for iteration in range(self.engine_props["max_iters"]):
            self.iteration = iteration

            self.stats_obj.iteration = iteration
            self.stats_obj.init_iter_stats()
            signal.signal(signal.SIGINT, self.stats_obj.save_stats)
            signal.signal(signal.SIGTERM, self.stats_obj.save_stats)

            if self.engine_props['route_method'] == 'ai':
                signal.signal(signal.SIGINT, self.ai_obj.save)
                signal.signal(signal.SIGTERM, self.ai_obj.save)

                self.ai_obj.reset_epsilon()
                self.ai_obj.episode = iteration
            if iteration == 0:
                print(f"Simulation started for Erlang: {self.engine_props['erlang']} "
                      f"simulation number: {self.engine_props['thread_num']}.")

            seed = self.engine_props["seeds"][iteration] if self.engine_props["seeds"] else iteration + 1
            self.generate_requests(seed)
            # TODO: Change back to one only
            req_num = 1
            # req_num = 5090
            for curr_time in self.reqs_dict:
                # TODO: Remove
                # if self.reqs_dict[curr_time]['req_id'] < 5090:
                #     continue
                # TODO: End remove
                req_type = self.reqs_dict[curr_time]["request_type"]
                if req_type == "arrival":

                    # TODO: Remove
                    # if req_num == 5090:
                    #     for link_tuple in self.net_spec_dict:
                    #         for core_num, core_arr in enumerate(self.net_spec_dict[link_tuple]['cores_matrix']):
                    #             self.net_spec_dict[link_tuple]['cores_matrix'][core_num] = core_arr.tolist()
                    #
                    #         self.net_spec_dict[link_tuple]['cores_matrix'] = self.net_spec_dict[link_tuple][
                    #             'cores_matrix'].tolist()
                    #
                    #     dict_for_json = {str(key): value for key, value in self.net_spec_dict.items()}
                    #     with open('new_network_5090.json', 'w') as file_path:
                    #         json.dump(dict_for_json, file_path)
                    #
                    #     exit()
                    # TODO: End remove

                    self.ai_obj.req_id = req_num
                    self.handle_arrival(curr_time=curr_time)

                    if self.engine_props['save_snapshots'] and req_num % self.engine_props['snapshot_step'] == 0:
                        self.stats_obj.update_snapshot(net_spec_dict=self.net_spec_dict, req_num=req_num)

                    req_num += 1
                elif req_type == "release":
                    self.handle_release(curr_time=curr_time)
                else:
                    raise NotImplementedError(f'Request type unrecognized. Expected arrival or release, '
                                              f'got: {req_type}')

            self.stats_obj.get_blocking()
            self.stats_obj.end_iter_update()
            # Some form of ML/RL is being used, ignore confidence intervals for training and testing
            if self.engine_props['ai_algorithm'] == 'None':
                if self.stats_obj.get_conf_inter():
                    self.ai_obj.save()
                    return

            if (iteration + 1) % self.engine_props['print_step'] == 0 or iteration == 0:
                self.stats_obj.print_iter_stats(max_iters=self.engine_props['max_iters'])

            self.ai_obj.save()
            self.stats_obj.save_stats()

        print(f"Erlang: {self.engine_props['erlang']} finished for "
              f"simulation number: {self.engine_props['thread_num']}.")
